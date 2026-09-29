"""SmartRecruiters : Sia Partners, Mirabaud, Sycomore AM.

Vérifié le 2026-09-29. L'API publique de SmartRecruiters
(`api.smartrecruiters.com`) est interdite à tout robot sauf LinkedIn : elle
n'est jamais appelée. La page carrières (`careers.smartrecruiters.com/<société>`)
n'a pas de robots.txt (le fichier renvoie une page HTML sans règle) : elle
liste les premières offres, cinquante au plus — les suivantes se chargent
par l'API interdite, on s'en passe. Chaque fiche (`jobs.smartrecruiters.com`,
sans robots.txt) porte son JobPosting : elle se lit comme un plan du site.
"""

from __future__ import annotations

import re
from datetime import datetime
from html import unescape

from .commun import Annonce, contrat
from .pays import depuis_lieu
from .plan_du_site import PlanDuSite
from .registre import Employeur

_OFFRE = re.compile(r'<li class="opening-job[^"]*".*?</li>', re.S)
_LIEN = re.compile(r'href="(https://jobs\.smartrecruiters\.com/[^/"]+/(\d+)-[^"]*)"')
_TITRE = re.compile(r'class="details-title[^"]*"[^>]*>(.*?)</', re.S)
_LIEU = re.compile(r'class="[^"]*(?:location|job-desc)[^"]*"[^>]*>(.*?)</', re.S)


def _propre(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment or "")).split())


class SmartRecruiters(PlanDuSite):
    cle = "smartrecruiters"

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        self.verifier(employeur.adresse)
        html = self.http.get(employeur.adresse, utiliser_cache=False, revalider=True).texte
        annonces, vus = [], set()
        for bloc_ in _OFFRE.findall(html or ""):
            lien, titre = _LIEN.search(bloc_), _TITRE.search(bloc_)
            if not lien or not titre or lien.group(2) in vus:
                continue
            vus.add(lien.group(2))
            lieu = _propre(_LIEU.search(bloc_).group(1)) if _LIEU.search(bloc_) else ""
            pays_ = depuis_lieu(lieu)
            if pays and pays_ and pays_ not in pays:
                continue
            annonces.append(Annonce(ident=lien.group(2), titre=_propre(titre.group(1)), url=lien.group(1),
                                    lieu=lieu, pays=pays_, contrat=contrat(_propre(titre.group(1)))))
        return annonces
