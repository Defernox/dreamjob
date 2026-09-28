"""Recruitee et Pinpoint : Meridiam, PAI Partners, Cinven.

Deux API publiques officielles, faites pour afficher les offres d'une
entreprise sur son propre site, qui donnent tout d'un coup — description
comprise. Vérifié le 2026-09-28 :

- Recruitee : `<site>/api/offers/`, date de publication et pays en code ISO ;
  robots.txt n'y interdit rien ;
- Pinpoint : `<site>/postings.json`, sans date de publication ; robots.txt
  n'interdit que l'espace d'administration et des annonces nommées.
"""

from __future__ import annotations

import re
from datetime import datetime

from .commun import Annonce, contrat, texte
from .logiciel import Logiciel
from .pays import depuis_iso, depuis_lieu
from .registre import Employeur


def _type(code: str) -> str:
    """« fulltime_permanent » → CDI, « fixed_term » → CDD, « internship » → Stage."""
    code = (code or "").lower()
    for motif, nom in (("intern", "Stage"), ("apprentic", "Alternance"), ("fixed", "CDD"),
                       ("temporary", "CDD"), ("permanent", "CDI")):
        if motif in code:
            return nom
    return ""


def _racine(employeur: Employeur) -> str:
    return re.match(r"https?://[^/]+", employeur.adresse).group(0)


class Recruitee(Logiciel):
    cle = "recruitee"

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        url = f"{_racine(employeur)}/api/offers/"
        self.verifier(url)
        r = self.http.get(url, entetes={"Accept": "application/json"}, utiliser_cache=False)
        annonces = []
        for o in (r.json_ or {}).get("offers") or [] if isinstance(r.json_, dict) else []:
            try:
                publiee = datetime.strptime(str(o.get("published_at") or o.get("created_at"))[:19],
                                            "%Y-%m-%d %H:%M:%S")
            except ValueError:
                publiee = None
            if publiee is not None and publiee < depuis:
                continue
            pays_ = depuis_iso(o.get("country_code")) or depuis_lieu(o.get("location"))
            if pays and pays_ and pays_ not in pays:
                continue
            annonces.append(Annonce(
                ident=str(o.get("id")), titre=(o.get("title") or "").strip(),
                url=o.get("careers_url") or "", lieu=o.get("location") or o.get("city") or "",
                pays=pays_, publiee_le=publiee,
                contrat=contrat(o.get("title") or "") or _type(o.get("employment_type_code")),
                description=texte("\n".join(filter(None, [o.get("description"), o.get("requirements")]))),
                complete=True,
            ))
        return [a for a in annonces if a.titre and a.url]


class Pinpoint(Logiciel):
    cle = "pinpoint"

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        url = f"{_racine(employeur)}/postings.json"
        self.verifier(url)
        r = self.http.get(url, entetes={"Accept": "application/json"}, utiliser_cache=False)
        annonces = []
        for o in (r.json_ or {}).get("data") or [] if isinstance(r.json_, dict) else []:
            lieu = o.get("location") or {}
            ville = (lieu.get("city") or lieu.get("name") or "") if isinstance(lieu, dict) else str(lieu)
            pays_ = depuis_lieu(ville)
            if pays and pays_ and pays_ not in pays:
                continue
            parties = [o.get(c) for c in ("description", "key_responsibilities", "skills_knowledge_expertise")]
            annonces.append(Annonce(
                ident=str(o.get("id")), titre=(o.get("title") or "").strip(),
                url=o.get("url") or f"{_racine(employeur)}{o.get('path') or ''}",
                lieu=ville, pays=pays_,
                contrat=contrat(o.get("title") or "", o.get("employment_type_text") or "")
                or _type(o.get("employment_type")),
                description=texte("\n".join(filter(None, parties))),
                complete=True,
            ))
        return [a for a in annonces if a.titre]
