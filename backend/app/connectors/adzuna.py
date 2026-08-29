"""Connecteur Adzuna — agrégateur international, API publique documentée.

Clés gratuites à créer sur https://developer.adzuna.com, puis dans `.env` :
    ADZUNA_APP_ID
    ADZUNA_APP_KEY

Adzuna expose un pays par requête. On interroge donc chaque pays accepté par le
profil, dans la limite de ceux qu'Adzuna couvre.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .base import (
    BaseConnector,
    ConnecteurNonConfigure,
    ErreurConnecteur,
    RawOffer,
    SearchQuery,
)
from .http import ErreurHttp

log = logging.getLogger("dreamjob.adzuna")

URL = "https://api.adzuna.com/v1/api/jobs/{pays}/search/{page}"
TAILLE_PAGE = 50          # maximum autorisé par l'API
PAGES_MAX = 5             # 250 offres par pays : au-delà, c'est du bruit

# Notre vocabulaire vers les codes pays d'Adzuna. Les pays absents de cette
# table ne sont pas couverts par Adzuna : on ne les interroge pas.
PAYS = {
    "Allemagne": "de", "Australie": "au", "Autriche": "at", "Belgique": "be",
    "Brésil": "br", "Canada": "ca", "Espagne": "es", "États-Unis": "us",
    "France": "fr", "Inde": "in", "Italie": "it", "Mexique": "mx",
    "Nouvelle-Zélande": "nz", "Pays-Bas": "nl", "Pologne": "pl",
    "Royaume-Uni": "gb", "Singapour": "sg", "Suisse": "ch",
}

# `contract_time` et `contract_type` d'Adzuna vers notre vocabulaire.
CONTRATS = {("permanent", None): "CDI", ("contract", None): "CDD"}


class AdzunaConnector(BaseConnector):
    cle = "adzuna"
    libelle = "Adzuna"

    def verifier_configuration(self) -> None:
        manquants = [n for n in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY")
                     if not self.reglages.secret(n)]
        if manquants:
            raise ConnecteurNonConfigure(
                f"Identifiants absents dans .env : {', '.join(manquants)}. "
                "Créez une clé gratuite sur developer.adzuna.com "
                "(page « Access details »)."
            )

    def _pays_interroges(self, query: SearchQuery) -> list[tuple[str, str]]:
        """(nom, code) des pays demandés qu'Adzuna couvre réellement."""
        souhaites = query.pays or ["France"]
        couverts = [(p, PAYS[p]) for p in souhaites if p in PAYS]
        ignores = [p for p in souhaites if p not in PAYS]
        if ignores:
            log.info("Adzuna ne couvre pas : %s", ", ".join(ignores))
        return couverts

    def fetch(self, query: SearchQuery) -> list[RawOffer]:
        self.verifier_configuration()
        identifiant = self.reglages.secret("ADZUNA_APP_ID")
        secret = self.reglages.secret("ADZUNA_APP_KEY")

        offres: list[RawOffer] = []
        pays = self._pays_interroges(query)
        if not pays:
            return offres

        # Le plafond se répartit entre les pays : demander 150 offres ne doit
        # pas en ramener 150 par pays.
        par_pays = max(TAILLE_PAGE, query.max_offres // len(pays))

        for nom, code in pays:
            recuperees = 0
            for page in range(1, PAGES_MAX + 1):
                if recuperees >= par_pays:
                    break
                params = {
                    "app_id": identifiant, "app_key": secret,
                    "results_per_page": min(TAILLE_PAGE, par_pays - recuperees),
                    "content-type": "application/json",
                }
                if query.mots_cles:
                    params["what"] = " ".join(query.mots_cles)

                try:
                    reponse = self.http.get(
                        URL.format(pays=code, page=page), params=params,
                        statuts_acceptes=(200,),
                    )
                except ErreurHttp as e:
                    if e.statut in (401, 403):
                        raise ErreurConnecteur(
                            "Adzuna refuse les identifiants. Vérifiez ADZUNA_APP_ID et "
                            "ADZUNA_APP_KEY dans .env."
                        ) from e
                    raise ErreurConnecteur(f"Recherche Adzuna ({nom}) en échec : {e}") from e

                lot = (reponse.json_ or {}).get("results") or []
                offres.extend(self._convertir(b, nom) for b in lot)
                recuperees += len(lot)
                log.info("Adzuna %s : %d offres (page %d)", nom, len(lot), page)
                if len(lot) < TAILLE_PAGE:
                    break

        return offres

    # ------------------------------------------------------------ conversion

    @staticmethod
    def _contrat(brute: dict) -> str:
        duree = (brute.get("contract_time") or "").lower()
        type_ = (brute.get("contract_type") or "").lower()
        if type_ == "permanent":
            return "CDI"
        if type_ == "contract":
            return "CDD"
        if duree == "part_time":
            return "Autre"
        titre = (brute.get("title") or "").lower()
        for motif, valeur in (("intern", "Stage"), ("stage", "Stage"),
                              ("apprenti", "Alternance"), ("alternance", "Alternance"),
                              ("v.i.e", "V.I.E"), ("vie ", "V.I.E")):
            if motif in titre:
                return valeur
        return "Autre"

    @staticmethod
    def _date(valeur: str | None) -> datetime | None:
        if not valeur:
            return None
        try:
            horodatage = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
        except ValueError:
            return None
        return horodatage.replace(tzinfo=None)

    def _convertir(self, brute: dict, pays: str) -> RawOffer:
        return RawOffer(
            source=self.cle,
            source_id=str(brute.get("id") or ""),
            titre=brute.get("title") or "",
            url=brute.get("redirect_url") or "",
            entreprise=(brute.get("company") or {}).get("display_name") or "",
            lieu=(brute.get("location") or {}).get("display_name") or "",
            pays=pays,
            type_contrat=self._contrat(brute),
            date_publication=self._date(brute.get("created")),
            description_brute=brute.get("description") or "",
            raw=brute,
        )
