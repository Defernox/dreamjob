"""Le plan du site et le balisage JobPosting : le format que Google exige.

Pour paraître dans Google for Jobs, un site carrières publie ses offres dans son
plan du site (`sitemap.xml`) et balise chaque fiche en JSON-LD `JobPosting`
(schema.org). C'est un format standard, pensé pour être lu par des programmes :
il marche quel que soit le logiciel, y compris sur les sites faits maison.

Société Générale, vérifié le 2026-09-28 : `robots.txt` interdit `/search/` —
la recherche du site n'est donc pas utilisée — et publie `sitemap.xml`, qui
liste 1 046 offres avec leur date de modification (vingt à cinquante nouvelles
par jour) ; chaque fiche porte son JobPosting.

Ce que la liste ne donne pas, l'adresse le donne : on y lit l'intitulé
(« …/offres-d-emploi/analyste-support-aux-operations-de-trading-2600032A-fr »),
assez pour la comparaison avec les recherches. La fiche n'est ouverte que pour
une offre nouvelle qui répond.

Options dans `employeurs.yaml` :
- `plan` : l'adresse du plan du site (sinon, celui que déclare robots.txt) ;
- `offres` : motif que suit l'adresse d'une offre ;
- `identifiant` : motif dont le premier groupe identifie l'offre — une même
  offre publiée en deux langues n'est alors lue qu'une fois ;
- `langue` : la version gardée quand il y en a deux.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import unescape
from urllib.parse import unquote, urljoin, urlparse

from .commun import Annonce, contrat, texte
from .logiciel import Logiciel
from .pays import depuis_iso, depuis_lieu, depuis_nom
from .registre import Employeur

_LOC = re.compile(r"<(sitemap|url)>\s*<loc>\s*([^<\s]+)\s*</loc>(?:\s*<lastmod>\s*([^<\s]+)\s*</lastmod>)?", re.S)
_JSONLD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
_CONTRATS = {"INTERN": "Stage", "INTERNSHIP": "Stage", "TEMPORARY": "CDD", "CONTRACTOR": "Freelance",
             "APPRENTICESHIP": "Alternance"}
PLANS_MAX = 20


def _date(valeur: str | None) -> datetime | None:
    if not valeur:
        return None
    valeur = valeur.strip().replace("/", "-")
    try:
        instant = datetime.fromisoformat(valeur)
    except ValueError:
        try:
            instant = datetime.strptime(valeur[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if instant.tzinfo is not None:
        instant = instant.astimezone(timezone.utc).replace(tzinfo=None)
    return instant


def jobposting(html: str) -> dict | None:
    """Le premier JobPosting des blocs JSON-LD d'une page (listes et `@graph`
    compris)."""
    for bloc in _JSONLD.findall(html):
        try:
            donnees = json.loads(bloc.strip())
        except json.JSONDecodeError:
            continue
        pile = donnees if isinstance(donnees, list) else [donnees]
        while pile:
            e = pile.pop(0)
            if not isinstance(e, dict):
                continue
            types = e.get("@type")
            if types == "JobPosting" or (isinstance(types, list) and "JobPosting" in types):
                return e
            pile.extend(e.get("@graph") or [])
    return None


def titre_de_l_adresse(url: str, identifiant: str | None) -> str:
    """« …/analyste-support-trading-2600032A-fr » → « analyste support trading »."""
    dernier = unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
    if identifiant and (m := re.search(identifiant, dernier)):
        dernier = dernier[:m.start()] + dernier[m.end():]
    dernier = re.sub(r"\.(?:html?|aspx?|php)$", "", dernier)
    return " ".join(re.sub(r"[-_+]+", " ", dernier).split())


def _lieu(e: dict) -> tuple[str, str]:
    """(ville, pays) d'un JobPosting, dont `jobLocation` peut être une liste."""
    lieux = e.get("jobLocation") or []
    lieux = lieux if isinstance(lieux, list) else [lieux]
    for lieu in lieux:
        adresse = (lieu or {}).get("address") or {} if isinstance(lieu, dict) else {}
        if isinstance(adresse, str):
            return adresse, depuis_lieu(adresse)
        ville = adresse.get("addressLocality") or ""
        pays = adresse.get("addressCountry") or ""
        if isinstance(pays, dict):
            pays = pays.get("name") or ""
        pays = depuis_iso(pays) if len(pays) == 2 else depuis_nom(pays)
        if ville or pays:
            return ville, pays or depuis_lieu(ville)
    return "", ""


class PlanDuSite(Logiciel):
    cle = "plan_du_site"

    def _plans(self, employeur: Employeur) -> list[str]:
        if plan := employeur.options.get("plan"):
            return [plan]
        racine = re.match(r"https?://[^/]+", employeur.adresse).group(0)
        regles = self.robots._pour(racine)
        declares = list(regles.site_maps() or []) if regles is not None else []
        return declares or [f"{racine}/sitemap.xml"]

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        motif = re.compile(employeur.options.get("offres", r"/(?:job|jobs|offre|offres|emploi|career|vacanc)"),
                           re.I)
        identifiant = employeur.options.get("identifiant")
        langue = employeur.options.get("langue")
        a_lire, lus = self._plans(employeur), 0
        vues: dict[str, Annonce] = {}
        while a_lire and lus < PLANS_MAX:
            plan = a_lire.pop(0)
            lus += 1
            self.verifier(plan)
            xml = self.http.get(plan, utiliser_cache=False).texte
            for balise, loc, modifie in _LOC.findall(xml):
                loc = urljoin(plan, loc)
                if balise == "sitemap":
                    # Un index de plans : on ne suit que ceux qui parlent d'offres.
                    if motif.search(loc) or "job" in loc.lower() or "offre" in loc.lower():
                        a_lire.append(loc)
                    continue
                if not motif.search(loc):
                    continue
                publiee = _date(modifie)
                if publiee is not None and publiee < depuis:
                    continue
                m = re.search(identifiant, loc) if identifiant else None
                ident = m.group(1) if m else urlparse(loc).path.rstrip("/").rsplit("/", 1)[-1]
                deja = vues.get(ident)
                # Une offre en deux langues : on garde la langue voulue.
                if deja and not (langue and loc.rstrip("/").endswith(f"-{langue}")):
                    continue
                vues[ident] = Annonce(ident=ident, titre=titre_de_l_adresse(loc, identifiant),
                                      url=loc, publiee_le=publiee)
        annonces = sorted(vues.values(), key=lambda a: a.publiee_le or datetime.min, reverse=True)
        return annonces

    def completer(self, employeur: Employeur, annonce: Annonce) -> Annonce:
        self.verifier(annonce.url)
        e = jobposting(self.http.get(annonce.url).texte)
        if e is None:
            return annonce
        # « Retail &amp; Online » : le titre JSON-LD est parfois échappé en HTML.
        annonce.titre = " ".join(unescape(str(e.get("title") or annonce.titre)).split())
        annonce.description = texte(str(e.get("description") or ""))
        annonce.lieu, annonce.pays = _lieu(e)
        annonce.publiee_le = _date(e.get("datePosted")) or annonce.publiee_le
        types = e.get("employmentType") or []
        types = [types] if isinstance(types, str) else types
        annonce.contrat = (contrat(annonce.titre, *types)
                           or next((_CONTRATS[t.upper()] for t in types if t.upper() in _CONTRATS), ""))
        annonce.brut["date_limite"] = e.get("validThrough")
        annonce.complete = True
        return annonce
