"""Beesite : Deutsche Bank.

Vérifié le 2026-09-28 : la page de recherche de careers.db.com appelle
`api-deutschebank.beesite.de/search/?data={…}`, qui n'a pas de robots.txt (rien
n'y est interdit). Tri par date de publication, cent offres par page ; la
description n'est que dans la fiche (`/jobhtml/<id>.json`). Les pays arrivent
en allemand (« Vereinigte Staaten von Amerika ») même en anglais, le contrat
aussi (« Unbefristet », qui n'est pas « befristet »).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import quote

from .commun import Annonce, contrat, texte
from .logiciel import Logiciel
from .pays import depuis_lieu, depuis_nom
from .registre import Employeur

PAR_PAGE = 100
CHAMPS = ["PositionID", "PositionTitle", "PositionURI", "OrganizationName", "PositionLocation.CountryName",
          "PositionLocation.CityName", "PublicationStartDate", "PositionOfferingType.Name",
          "CareerLevel.Name"]


def _premier(valeur, cle: str) -> str:
    """Beesite range les champs en listes d'objets : `[{"Name": "…"}]`."""
    if isinstance(valeur, list):
        valeur = valeur[0] if valeur else {}
    return str((valeur or {}).get(cle) or "") if isinstance(valeur, dict) else str(valeur or "")


class Beesite(Logiciel):
    cle = "beesite"

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        api = re.match(r"https?://[^/]+", employeur.adresse).group(0)
        publique = employeur.options.get("fiche", "")
        annonces: list[Annonce] = []
        for page in range(pages_max):
            donnees = json.dumps({
                "LanguageCode": employeur.options.get("langue", "en"),
                "SearchParameters": {"FirstItem": 1 + page * PAR_PAGE, "CountItem": PAR_PAGE,
                                     "MatchedObjectDescriptor": CHAMPS,
                                     "Sort": [{"Criterion": "PublicationStartDate", "Direction": "DESC"}]},
                "SearchCriteria": [],
            }, separators=(",", ":"))
            url = f"{api}/search/?data={quote(donnees)}"
            self.verifier(url)
            r = self.http.get(url, entetes={"Accept": "application/json"}, utiliser_cache=False)
            resultat = (r.json_ or {}).get("SearchResult") or {} if isinstance(r.json_, dict) else {}
            items = resultat.get("SearchResultItems") or []
            trop_vieille = False
            for item in items:
                o = item.get("MatchedObjectDescriptor") or {}
                try:
                    publiee = datetime.strptime(str(o.get("PublicationStartDate"))[:10], "%Y-%m-%d")
                except ValueError:
                    publiee = None
                if publiee is not None and publiee < depuis.replace(hour=0, minute=0, second=0):
                    trop_vieille = True
                    break
                ville = _premier(o.get("PositionLocation"), "CityName")
                pays_ = depuis_nom(_premier(o.get("PositionLocation"), "CountryName")) or depuis_lieu(ville)
                if pays and pays_ and pays_ not in pays:
                    continue
                ident = str(o.get("PositionID") or "")
                titre = str(o.get("PositionTitle") or "").strip()
                annonces.append(Annonce(
                    ident=ident, titre=titre,
                    url=publique.format(id=ident) if publique else f"{api}{o.get('PositionURI') or ''}",
                    lieu=ville, pays=pays_, publiee_le=publiee,
                    contrat=contrat(titre, _premier(o.get("PositionOfferingType"), "Name")),
                ))
            if trop_vieille or len(items) < PAR_PAGE:
                break
        return [a for a in annonces if a.titre and a.ident]

    def completer(self, employeur: Employeur, annonce: Annonce) -> Annonce:
        """La recherche ne donne pas la description : la fiche est à
        `/jobhtml/<id>.json`, en HTML."""
        api = re.match(r"https?://[^/]+", employeur.adresse).group(0)
        url = f"{api}/jobhtml/{annonce.ident}.json"
        self.verifier(url)
        r = self.http.get(url, entetes={"Accept": "application/json"})
        html = (r.json_ or {}).get("html") if isinstance(r.json_, dict) else None
        if html:
            annonce.description = texte(html)
            if re.search(r"Regular/Temporary:\s*</strong>\s*Temporary", html):
                annonce.contrat = annonce.contrat or "CDD"
        annonce.complete = True
        return annonce
