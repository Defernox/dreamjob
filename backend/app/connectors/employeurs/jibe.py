"""Jibe (iCIMS) : AXA.

Vérifié le 2026-09-28 sur careers.axa.com : `robots.txt` autorise tout mais
demande cinq secondes entre deux requêtes (`crawl-delay: 5`), ce que le client
respecte. L'interface que la page appelle (`/api/jobs`) trie par date de
publication, cent offres par page, et donne tout — pays en code ISO, contrat
(`INTERN`…), **description complète** : aucune fiche à ouvrir.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .commun import Annonce, contrat, texte
from .logiciel import Logiciel
from .pays import depuis_iso, depuis_lieu
from .registre import Employeur

PAR_PAGE = 100
_CONTRATS = {"INTERN": "Stage", "INTERNSHIP": "Stage", "TEMPORARY": "CDD", "APPRENTICE": "Alternance",
             "APPRENTICESHIP": "Alternance", "CONTRACTOR": "Freelance"}


def _date(valeur: str | None) -> datetime | None:
    try:
        instant = datetime.strptime(valeur or "", "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None
    return instant.astimezone(timezone.utc).replace(tzinfo=None)


class Jibe(Logiciel):
    cle = "jibe"

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        base = re.match(r"https?://[^/]+", employeur.adresse).group(0)
        chemin = employeur.adresse.rstrip("/")
        annonces: list[Annonce] = []
        for page in range(1, pages_max + 1):
            url = (f"{base}/api/jobs?page={page}&limit={PAR_PAGE}&sortBy=posted_date"
                   f"&descending=true&internal=false")
            self.verifier(url)
            r = self.http.get(url, entetes={"Accept": "application/json"}, utiliser_cache=False, revalider=True)
            offres = [o.get("data") or {} for o in (r.json_ or {}).get("jobs") or []] if isinstance(r.json_, dict) else []
            trop_vieille = False
            for o in offres:
                publiee = _date(o.get("posted_date"))
                if publiee is not None and publiee < depuis:
                    trop_vieille = True
                    break
                pays_ = depuis_iso(o.get("country_code")) or depuis_lieu(o.get("full_location"))
                if pays and pays_ and pays_ not in pays:
                    continue
                type_ = str(o.get("employment_type") or "").upper()
                parties = [o.get(c) for c in ("description", "responsibilities", "qualifications") if o.get(c)]
                annonces.append(Annonce(
                    ident=str(o.get("req_id") or o.get("slug")),
                    titre=(o.get("title") or "").strip(),
                    url=f"{chemin}/jobs/{o.get('slug')}?lang={o.get('language') or 'en-us'}",
                    lieu=o.get("full_location") or o.get("city") or "",
                    pays=pays_, publiee_le=publiee,
                    contrat=contrat(o.get("title") or "") or _CONTRATS.get(type_, ""),
                    description=texte("\n".join(parties)),
                    complete=True,
                ))
            if trop_vieille or len(offres) < PAR_PAGE:
                break
        return [a for a in annonces if a.titre]
