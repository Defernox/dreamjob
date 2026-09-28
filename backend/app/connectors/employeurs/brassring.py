"""BrassRing (Infinite) : UBS.

Vérifié le 2026-09-28 sur jobs.ubs.com, qui n'a pas de robots.txt (rien n'y
est interdit). La page de recherche embarque ses cinquante offres les plus
récentes dans un champ caché (`preLoadJSON`) : les suivantes demanderaient
une requête munie d'un jeton de session, qu'on ne fabrique pas. Cinquante
offres couvrent environ cinq jours chez UBS — assez pour la veille et pour le
scan quotidien, qui passe chaque jour.

La fiche est la même page, `PageType=JobDetails`, découpée en sections
(responsabilités, équipe, compétences…).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from html import unescape

from .commun import Annonce, contrat, texte
from .logiciel import Logiciel
from .pays import depuis_lieu, depuis_nom
from .registre import Employeur

_PRECHARGE = re.compile(r'id="preLoadJSON"[^>]*?value="([^"]*)"')
# Les champs techniques d'une fiche : tout le reste est du texte d'annonce.
_TECHNIQUES = {"reqid", "hotjob", "clientid", "siteid", "gqid", "jobreqlanguage", "latitude",
               "longitude", "lastupdated", "jobtitle", "formtext23", "formtext21", "formtext2",
               "department", "city", "job type", "job reference #"}


def _precharge(html: str) -> dict:
    m = _PRECHARGE.search(html or "")
    try:
        return json.loads(unescape(m.group(1))) if m else {}
    except json.JSONDecodeError:
        return {}


def _questions(elements: list) -> dict[str, str]:
    return {str(q.get("QuestionName") or q.get("VerityZone") or ""): str(q.get("Value") or q.get("AnswerValue") or "")
            for q in elements or [] if isinstance(q, dict)}


class BrassRing(Logiciel):
    cle = "brassring"

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        url = f"{employeur.adresse}&PageType=searchResults"
        self.verifier(url)
        donnees = _precharge(self.http.get(url, utiliser_cache=False).texte)
        offres = ((donnees.get("searchResultsResponse") or {}).get("Jobs") or {}).get("Job") or []
        champ_pays = employeur.options.get("champ_pays", "formtext23")
        annonces = []
        for o in offres:
            q = _questions(o.get("Questions"))
            try:
                publiee = datetime.strptime(q.get("lastupdated", ""), "%d-%b-%Y")
            except ValueError:
                publiee = None
            if publiee is not None and publiee < depuis.replace(hour=0, minute=0, second=0):
                continue
            pays_ = depuis_nom(q.get(champ_pays)) or depuis_lieu(q.get("formtext2"))
            if pays and pays_ and pays_ not in pays:
                continue
            annonces.append(Annonce(
                ident=q.get("reqid", ""), titre=q.get("jobtitle", "").strip(),
                url=f"{employeur.adresse}&PageType=JobDetails&jobid={q.get('reqid', '')}",
                lieu=q.get("formtext2", ""), pays=pays_, publiee_le=publiee,
                contrat=contrat(q.get("jobtitle", "")),
            ))
        return [a for a in annonces if a.titre and a.ident]

    def completer(self, employeur: Employeur, annonce: Annonce) -> Annonce:
        self.verifier(annonce.url)
        fiche = _precharge(self.http.get(annonce.url).texte).get("Jobdetails") or {}
        q = _questions(fiche.get("JobDetailQuestions"))
        if not q:
            return annonce
        sections = [f"<h3>{nom}</h3>{valeur}" for nom, valeur in q.items()
                    if nom.lower() not in _TECHNIQUES and len(valeur) > 40]
        annonce.description = texte("".join(sections))
        annonce.lieu = q.get("City") or annonce.lieu
        champ_pays = employeur.options.get("champ_pays", "formtext23")
        annonce.pays = depuis_nom(q.get(champ_pays)) or annonce.pays or depuis_lieu(annonce.lieu)
        annonce.contrat = contrat(annonce.titre, q.get("Job Type", "")) or annonce.contrat
        annonce.complete = True
        return annonce
