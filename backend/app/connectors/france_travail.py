"""Connecteur France Travail — API officielle « Offres d'emploi v2 ».

Authentification OAuth2 « client credentials » : l'application s'authentifie
elle-même, aucun compte utilisateur n'est impliqué.

Identifiants à créer sur https://francetravail.io (Mes applications → souscrire
à l'API Offres d'emploi v2), puis dans `.env` :
    FRANCE_TRAVAIL_CLIENT_ID
    FRANCE_TRAVAIL_CLIENT_SECRET
"""

from __future__ import annotations

import logging
import time
import unicodedata
from datetime import datetime, timezone

from .base import (
    BaseConnector,
    ConnecteurNonConfigure,
    ErreurConnecteur,
    RawOffer,
    SearchQuery,
)
from .http import ErreurHttp

log = logging.getLogger("dreamjob.france_travail")

# --- Constantes de l'API, regroupées : un changement chez France Travail se
#     corrige ici et nulle part ailleurs. -------------------------------------
URL_TOKEN = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
REALM = "/partenaire"
SCOPE = "api_offresdemploiv2 o2dsoffre"
URL_RECHERCHE = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"

# L'API plafonne à 150 offres par appel et refuse un décalage au-delà de 3000.
TAILLE_PAGE = 150
DECALAGE_MAX = 3000

# Codes `typeContrat` de France Travail vers notre vocabulaire (models/enums.py).
CONTRATS = {
    "CDI": "CDI",
    "DIN": "CDI",          # CDI intérimaire
    "CDD": "CDD",
    "SAI": "CDD",          # saisonnier
    "DDI": "CDD",          # CDD insertion
    "MIS": "Intérim",
    "TTI": "Intérim",
    "STG": "Stage",
    "CCE": "Freelance",    # profession commerciale
    "FRA": "Freelance",    # franchise
    "LIB": "Freelance",    # profession libérale
    "REP": "Autre",        # reprise d'entreprise
}
# `natureContrat` : l'alternance ne se lit pas dans typeContrat.
NATURES_ALTERNANCE = {"E1", "E2"}   # apprentissage, professionnalisation

# Notre vocabulaire vers le filtre `typeContrat` envoyé à l'API.
FILTRE_CONTRAT = {"CDI": "CDI", "CDD": "CDD", "Intérim": "MIS", "Stage": "STG"}


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c)).lower()


class FranceTravailConnector(BaseConnector):
    cle = "france_travail"
    libelle = "France Travail"

    def __init__(self, http, reglages) -> None:
        super().__init__(http, reglages)
        self._token: str | None = None
        self._token_expire_a: float = 0.0

    # ---------------------------------------------------------- configuration

    def verifier_configuration(self) -> None:
        manquants = [
            nom for nom in ("FRANCE_TRAVAIL_CLIENT_ID", "FRANCE_TRAVAIL_CLIENT_SECRET")
            if not self.reglages.secret(nom)
        ]
        if manquants:
            raise ConnecteurNonConfigure(
                f"Identifiants absents dans .env : {', '.join(manquants)}. "
                "Créez une application sur francetravail.io et souscrivez à "
                "l'API « Offres d'emploi v2 »."
            )

    # -------------------------------------------------------------------- auth

    def _jeton(self) -> str:
        """Jeton d'accès, gardé en mémoire jusqu'à 60 s avant son expiration."""
        if self._token and time.monotonic() < self._token_expire_a:
            return self._token

        self.verifier_configuration()
        try:
            reponse = self.http.post(
                URL_TOKEN,
                params={"realm": REALM},
                donnees={
                    "grant_type": "client_credentials",
                    "client_id": self.reglages.secret("FRANCE_TRAVAIL_CLIENT_ID"),
                    "client_secret": self.reglages.secret("FRANCE_TRAVAIL_CLIENT_SECRET"),
                    "scope": SCOPE,
                },
                entetes={"Content-Type": "application/x-www-form-urlencoded"},
                utiliser_cache=False,     # un jeton ne se met jamais en cache disque
            )
        except ErreurHttp as e:
            if e.statut in (400, 401):
                raise ErreurConnecteur(
                    "France Travail refuse les identifiants. Vérifiez "
                    "FRANCE_TRAVAIL_CLIENT_ID / _SECRET dans .env, et que votre "
                    "application est bien souscrite à l'API « Offres d'emploi v2 »."
                ) from e
            raise ErreurConnecteur(f"Authentification France Travail impossible : {e}") from e

        charge = reponse.json_ or {}
        jeton = charge.get("access_token")
        if not jeton:
            raise ErreurConnecteur("France Travail n'a pas renvoyé de jeton d'accès.")

        self._token = jeton
        self._token_expire_a = time.monotonic() + max(int(charge.get("expires_in", 1500)) - 60, 60)
        return jeton

    # ---------------------------------------------------------------- requête

    def _parametres(self, query: SearchQuery, debut: int, fin: int) -> dict:
        params: dict[str, str] = {"range": f"{debut}-{fin}"}
        if query.mots_cles:
            params["motsCles"] = ",".join(query.mots_cles)
        if query.departement:
            params["departement"] = query.departement
        if query.publiee_depuis_jours:
            # L'API n'accepte que ces paliers. On arrondit vers le HAUT :
            # ramener 5 jours à 3 ferait perdre deux jours d'offres, alors que
            # 7 en ramène simplement quelques-unes de trop.
            paliers = [1, 3, 7, 14, 31]
            demande = query.publiee_depuis_jours
            params["publieeDepuis"] = str(
                next((p for p in paliers if p >= demande), paliers[-1])
            )
        codes = [FILTRE_CONTRAT[c] for c in query.contrats if c in FILTRE_CONTRAT]
        if len(codes) == 1:
            # L'API ne prend qu'un type à la fois : au-delà, on récupère tout et
            # on filtre après coup plutôt que de multiplier les requêtes.
            params["typeContrat"] = codes[0]
        return params

    def fetch(self, query: SearchQuery) -> list[RawOffer]:
        self.verifier_configuration()
        entetes = {"Authorization": f"Bearer {self._jeton()}", "Accept": "application/json"}

        offres: list[RawOffer] = []
        debut = 0
        plafond = min(query.max_offres, DECALAGE_MAX)
        while debut < plafond:
            fin = min(debut + TAILLE_PAGE - 1, plafond - 1)
            try:
                reponse = self.http.get(
                    URL_RECHERCHE,
                    params=self._parametres(query, debut, fin),
                    entetes=entetes,
                    # 204 = aucun résultat, 206 = page partielle : les deux sont normaux.
                    statuts_acceptes=(200, 204, 206),
                )
            except ErreurHttp as e:
                raise ErreurConnecteur(f"Recherche France Travail en échec : {e}") from e

            if reponse.statut == 204:
                break

            lot = (reponse.json_ or {}).get("resultats") or []
            offres.extend(self._convertir(brute) for brute in lot)
            log.info("France Travail : %d offres (plage %d-%d)", len(lot), debut, fin)

            if len(lot) < TAILLE_PAGE:
                break
            debut = fin + 1

        return offres

    # ------------------------------------------------------------ conversion

    @staticmethod
    def _contrat(brute: dict) -> str:
        if brute.get("alternance") or brute.get("natureContrat") in NATURES_ALTERNANCE:
            return "Alternance"
        code = (brute.get("typeContrat") or "").upper()
        if code in CONTRATS:
            return CONTRATS[code]
        # Repli sur le libellé : les codes évoluent, les mots restent.
        # Sans accents : certaines sources les perdent en route.
        libelle = _sans_accents(brute.get("typeContratLibelle") or "")
        for motif, valeur in (("apprentissage", "Alternance"),
                              ("professionnalisation", "Alternance"),
                              ("stage", "Stage"), ("interim", "Intérim"),
                              ("indeterminee", "CDI"), ("determinee", "CDD")):
            if motif in libelle:
                return valeur
        return "Autre"

    @staticmethod
    def _date(valeur: str | None) -> datetime | None:
        """ISO avec fuseau vers UTC naïf (convention de la base, cf. CLAUDE.md)."""
        if not valeur:
            return None
        try:
            horodatage = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
        except ValueError:
            return None
        if horodatage.tzinfo is None:
            return horodatage
        return horodatage.astimezone(timezone.utc).replace(tzinfo=None)

    def _convertir(self, brute: dict) -> RawOffer:
        lieu = brute.get("lieuTravail") or {}
        entreprise = brute.get("entreprise") or {}
        origine = brute.get("origineOffre") or {}
        identifiant = str(brute.get("id") or "")
        url_defaut = f"https://candidat.francetravail.fr/offres/recherche/detail/{identifiant}"

        return RawOffer(
            source=self.cle,
            source_id=identifiant,
            titre=brute.get("intitule") or "",
            url=origine.get("urlOrigine") or url_defaut,
            entreprise=entreprise.get("nom") or "",
            lieu=lieu.get("libelle") or "",
            # L'API est franco-centrée ; les rares offres hors France se
            # repèrent au scoring, sur le libellé du lieu.
            pays="France",
            type_contrat=self._contrat(brute),
            date_publication=self._date(brute.get("dateCreation")),
            description_brute=brute.get("description") or "",
            raw=brute,
        )
