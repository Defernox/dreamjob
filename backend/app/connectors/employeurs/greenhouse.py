"""Greenhouse : Point72, Man Group, IMC, Flow Traders, Jump Trading, EQT…

Une API publique officielle, documentée pour que chacun affiche les offres
d'une entreprise (`boards-api.greenhouse.io/v1/boards/<jeton>/jobs`). Vérifié
le 2026-09-28 : `robots.txt` n'y interdit que `/embed/` ; l'hôte européen
(`boards-api.eu…`) n'existe pas, l'hôte principal sert aussi les tableaux
hébergés en Europe.

Toute la liste tient en une réponse, avec la date de première publication ; la
description ne vient qu'avec la fiche. Un lieu peut citer plusieurs villes
(« New York, London, Singapore ») : l'offre est retenue si l'une est voulue.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
from urllib.parse import urlparse

from .commun import Annonce, contrat, texte
from .logiciel import Logiciel
from .pays import pays_possibles
from .registre import Employeur

API = "https://boards-api.greenhouse.io/v1/boards"


def jeton(employeur: Employeur) -> str:
    """`https://job-boards.eu.greenhouse.io/imc` → « imc »."""
    if j := employeur.options.get("jeton"):
        return str(j)
    segments = [s for s in urlparse(employeur.adresse).path.split("/") if s]
    if not segments:
        raise ValueError(f"Adresse Greenhouse sans tableau : {employeur.adresse}")
    return segments[0]


def _date(valeur: str | None) -> datetime | None:
    try:
        instant = datetime.fromisoformat(valeur) if valeur else None
    except ValueError:
        return None
    if instant is not None and instant.tzinfo is not None:
        instant = instant.astimezone(timezone.utc).replace(tzinfo=None)
    return instant


class Greenhouse(Logiciel):
    cle = "greenhouse"

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        url = f"{API}/{jeton(employeur)}/jobs"
        self.verifier(url)
        r = self.http.get(url, utiliser_cache=False)
        annonces = []
        for o in (r.json_ or {}).get("jobs") or [] if isinstance(r.json_, dict) else []:
            publiee = _date(o.get("first_published") or o.get("updated_at"))
            if publiee is not None and publiee < depuis:
                continue
            lieu = (o.get("location") or {}).get("name") or ""
            possibles = pays_possibles(lieu)
            if pays and possibles and not set(possibles) & set(pays):
                continue
            annonces.append(Annonce(
                ident=str(o.get("id")),
                titre=(o.get("title") or "").strip(),
                url=o.get("absolute_url") or "",
                lieu=lieu,
                pays=next((p for p in possibles if p in pays), possibles[0] if possibles else ""),
                publiee_le=publiee,
                contrat=contrat(o.get("title") or ""),
            ))
        annonces.sort(key=lambda a: a.publiee_le or datetime.min, reverse=True)
        return [a for a in annonces if a.titre and a.url]

    def completer(self, employeur: Employeur, annonce: Annonce) -> Annonce:
        url = f"{API}/{jeton(employeur)}/jobs/{annonce.ident}"
        self.verifier(url)
        r = self.http.get(url)
        d = r.json_ if isinstance(r.json_, dict) else {}
        # Le contenu arrive en HTML échappé (« &lt;p&gt; ») : on le déséchappe
        # une fois avant d'en retirer les balises.
        annonce.description = texte(unescape(d.get("content") or ""))
        temps = " ".join(str(m.get("value") or "") for m in d.get("metadata") or []
                         if "type" in str(m.get("name") or "").lower())
        annonce.contrat = contrat(annonce.titre, temps) or annonce.contrat
        annonce.complete = True
        return annonce
