"""Connecteur Civiweb / Business France — missions V.I.E et V.I.A.

**Ce qui a été vérifié avant d'écrire ce connecteur** (2026-08-29) :

- `robots.txt` de mon-vie-via.businessfrance.fr n'interdit que `/refresh` ;
- les mentions légales ne comportent aucune clause sur l'extraction
  automatisée, la réutilisation ou les robots ;
- l'endpoint interrogé est celui que le site utilise lui-même, et sa clé est
  publiée en clair dans la configuration front livrée à chaque navigateur.

Elle est donc reprise ici comme valeur par défaut, surchargeable par
`CIVIWEB_API_KEY` dans `.env` si Business France la change.
"""

from __future__ import annotations

import logging
import unicodedata
from datetime import datetime

from ..models.enums import PAYS_FILTRES
from .base import BaseConnector, ErreurConnecteur, RawOffer, SearchQuery
from .http import ErreurHttp

log = logging.getLogger("dreamjob.civiweb")

URL_RECHERCHE = "https://civiweb-api-prd.azurewebsites.net/api/Offers/search"
URL_OFFRE = "https://mon-vie-via.businessfrance.fr/offres/{identifiant}"
CLE_PUBLIQUE = "l+KwpoLPiXlsjxNT/NQ2iOFz8+iuygxAODs9FeAEWYM="

TAILLE_PAGE = 50   # l'API accepte davantage, mais on reste discret


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in decompose if not unicodedata.combining(c)).lower()


# Le pays arrive en majuscules sans accents (« ETATS-UNIS ») : on le rapproche
# de notre vocabulaire une fois les deux normalisés.
_PAYS_NORMALISES = {_sans_accents(p): p for p in PAYS_FILTRES}
# Quelques libellés que la normalisation seule ne rapproche pas.
_ALIAS_PAYS = {
    "royaume uni": "Royaume-Uni", "grande-bretagne": "Royaume-Uni",
    "etats unis": "États-Unis",
    "emirats arabes unis": "Émirats arabes unis",
    "cote d'ivoire": "Côte d'Ivoire", "cote d ivoire": "Côte d'Ivoire",
    "ile maurice": "Île Maurice", "maurice": "Île Maurice",
    "republique tcheque": "Tchéquie", "tcheque": "Tchéquie",
    "pays bas": "Pays-Bas", "hong-kong": "Hong Kong",
}


class CiviwebConnector(BaseConnector):
    cle = "civiweb"
    libelle = "Civiweb (V.I.E)"

    def _cle_api(self) -> str:
        return self.reglages.secret("CIVIWEB_API_KEY") or CLE_PUBLIQUE

    def fetch(self, query: SearchQuery) -> list[RawOffer]:
        entetes = {"Content-Type": "application/json", "x-api-key": self._cle_api()}
        offres: list[RawOffer] = []
        debut = 0

        while debut < query.max_offres:
            corps = {"limit": min(TAILLE_PAGE, query.max_offres - debut), "skip": debut}
            if query.mots_cles:
                corps["query"] = " ".join(query.mots_cles)

            try:
                reponse = self.http.requete(
                    "POST", URL_RECHERCHE, corps_json=corps, entetes=entetes,
                    statuts_acceptes=(200, 204),
                )
            except ErreurHttp as e:
                if e.statut == 401:
                    raise ErreurConnecteur(
                        "Civiweb refuse la clé publique du site : elle a sans doute été "
                        "changée. Relevez la nouvelle valeur dans la configuration front "
                        "de mon-vie-via.businessfrance.fr et placez-la dans .env "
                        "(CIVIWEB_API_KEY)."
                    ) from e
                raise ErreurConnecteur(f"Recherche Civiweb en échec : {e}") from e

            lot = (reponse.json_ or {}).get("result") or []
            offres.extend(self._convertir(b) for b in lot)
            log.info("Civiweb : %d offres (a partir de %d)", len(lot), debut)

            if len(lot) < corps["limit"]:
                break
            debut += len(lot)

        return offres

    # ------------------------------------------------------------ conversion

    @staticmethod
    def _pays(brute: dict) -> str:
        brut = _sans_accents(brute.get("countryName") or "").strip()
        if not brut:
            return ""
        if brut in _PAYS_NORMALISES:
            return _PAYS_NORMALISES[brut]
        if brut in _ALIAS_PAYS:
            return _ALIAS_PAYS[brut]
        # Pays hors de notre liste : on garde le libellé d'origine plutôt que de
        # le perdre. Le critère pays le comptera simplement comme non accepté.
        return (brute.get("countryName") or "").title()

    @staticmethod
    def _date(valeur: str | None) -> datetime | None:
        if not valeur:
            return None
        try:
            horodatage = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
        except ValueError:
            return None
        return horodatage.replace(tzinfo=None)

    def _convertir(self, brute: dict) -> RawOffer:
        identifiant = str(brute.get("id") or "")
        # Le descriptif et le profil recherché sont deux champs distincts ; le
        # scoring a besoin des deux pour retrouver les compétences.
        description = "\n\n".join(filter(None, [
            brute.get("missionDescription"), brute.get("missionProfile"),
        ]))
        # V.I.A existe aussi, mais notre vocabulaire ne connaît que V.I.E.
        type_mission = (brute.get("missionType") or "").upper()

        return RawOffer(
            source=self.cle,
            source_id=identifiant,
            titre=brute.get("missionTitle") or "",
            url=URL_OFFRE.format(identifiant=identifiant),
            entreprise=brute.get("organizationName") or "",
            lieu=brute.get("cityName") or "",
            pays=self._pays(brute),
            type_contrat="V.I.E" if type_mission in ("VIE", "VIA") else "Autre",
            date_publication=self._date(brute.get("creationDate")),
            description_brute=description,
            raw=brute,
        )
