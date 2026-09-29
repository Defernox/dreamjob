"""Cornerstone OnDemand (csod.com) : AFD, Spuerkeess, Groupe Crystal.

La page carrières (`<société>.csod.com/ux/ats/careersite/<n>/home`) ne contient
pas les offres : son script les demande à `rec-job-search/external/jobs`, sur
l'hôte régional de Cornerstone (`uk.api.csod.com`…), avec le jeton que la page
elle-même embarque pour tout visiteur. On fait exactement ce que fait la page :
on la lit, on reprend son jeton, on pose la même question. Aucun compte, aucune
connexion. La réponse donne l'intitulé, le lieu, les dates de publication et
d'expiration, et la description entière.

Vérifié le 2026-09-29 (AFD) : robots.txt de `afd.csod.com` ne contient que
`Crawl-delay: 10`, respecté ; celui de l'hôte régional n'existe pas (404). La
fiche publique porte un JobPosting.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from .commun import Annonce, contrat, date_jma, texte
from .pays import depuis_iso, depuis_lieu
from .plan_du_site import PlanDuSite
from .registre import Employeur

PAR_PAGE = 25
_JETON = re.compile(r'"token":"(eyJ[^"]+)"')
_NUAGE = re.compile(r'"cloud":"(https://[^"]+)"')
_CULTURE_ID = re.compile(r'"cultureID":(\d+)')
_CULTURE = re.compile(r'"cultureName":"([\w-]+)"')


def _jour(brut: str, culture: str) -> datetime | None:
    """« 28/09/2026 » en français, « 9/28/2026 » en anglais américain."""
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", brut or "")
    if not m:
        return None
    a, b, annee = (int(x) for x in m.groups())
    jour, mois = (b, a) if culture.lower() == "en-us" else (a, b)
    return date_jma(jour, mois, annee)


class Cornerstone(PlanDuSite):
    cle = "cornerstone"

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        self.verifier(employeur.adresse)
        page = self.http.get(employeur.adresse, utiliser_cache=False).texte or ""
        jeton, nuage = _JETON.search(page), _NUAGE.search(page)
        if not jeton or not nuage:
            return []
        site = int(re.search(r"/careersite/(\d+)", employeur.adresse).group(1))
        culture = (_CULTURE.search(page) or [None, "fr-FR"])[1]
        culture_id = int((_CULTURE_ID.search(page) or [None, "13"])[1])
        societe = (parse_qs(urlparse(employeur.adresse).query).get("c") or [""])[0]
        base = re.match(r"https?://[^/]+", employeur.adresse).group(0)
        url = f"{nuage.group(1).rstrip('/')}/rec-job-search/external/jobs"
        self.verifier(url)

        annonces: list[Annonce] = []
        for numero in range(1, pages_max + 1):
            r = self.http.post(url, corps_json={
                "careerSiteId": site, "careerSitePageId": site, "pageNumber": numero,
                "pageSize": PAR_PAGE, "cultureId": culture_id, "searchText": "",
                "cultureName": culture, "states": [], "countryCodes": [], "cities": [],
                "placeID": "", "radius": None, "postingsWithinDays": None,
                "customFieldCheckboxKeys": [], "customFieldDropdowns": [], "customFieldRadios": [],
            }, entetes={"Authorization": f"Bearer {jeton.group(1)}", "Accept": "application/json"},
                utiliser_cache=False)
            donnees = (r.json_ or {}).get("data") or {} if isinstance(r.json_, dict) else {}
            lot = donnees.get("requisitions") or []
            for o in lot:
                publiee = _jour(str(o.get("postingEffectiveDate") or ""), culture)
                if publiee is not None and publiee < depuis.replace(hour=0, minute=0, second=0):
                    continue
                lieu = (o.get("locations") or [{}])[0] or {}
                ville = str(lieu.get("city") or "")
                pays_ = depuis_iso(str(lieu.get("country") or "")) or depuis_lieu(ville)
                if pays and pays_ and pays_ not in pays:
                    continue
                ident = str(o.get("requisitionId") or "")
                titre = " ".join(str(o.get("displayJobTitle") or "").split())
                description = texte(o.get("externalDescription") or "")
                annonce = Annonce(
                    ident=ident, titre=titre,
                    url=f"{base}/ux/ats/careersite/{site}/home/requisition/{ident}?c={societe}",
                    lieu=ville, pays=pays_, publiee_le=publiee, contrat=contrat(titre),
                    description=description, complete=len(description) >= 400)
                expiration = _jour(str(o.get("postingExpirationDate") or ""), culture)
                annonce.brut["date_limite"] = expiration.date().isoformat() if expiration else None
                annonces.append(annonce)
            # Sans total connu, seule une page incomplète dit la fin : un total
            # absent valait zéro, et la lecture s'arrêtait à la première page.
            total = int(donnees.get("totalCount") or 0)
            if len(lot) < PAR_PAGE or (total and numero * PAR_PAGE >= total):
                break
        return [a for a in annonces if a.titre and a.ident]

    def completer(self, employeur: Employeur, annonce: Annonce) -> Annonce:
        if annonce.complete:
            return annonce
        resume = annonce.description
        fiche = super().completer(employeur, annonce)
        fiche.description = fiche.description or resume
        return fiche
