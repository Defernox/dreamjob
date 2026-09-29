"""Le groupe BPCE : Natixis CIB, Natixis IM, Caisses d'Épargne, Banques
Populaires, BRED, Palatine, Oney… sur un seul site, recrutement.bpce.fr.

Vérifié le 2026-09-28. Le site est une application JavaScript sur WordPress :

- `robots.txt` interdit la recherche d'offres et les listes par lieu, entité
  ou catégorie (`/recherche-d'offres`, `/emploi/`, `/lieu/`, `/category/`…).
  Elles ne sont **jamais** utilisées, pas plus que l'interface de recherche
  qui les alimente (`bpce/v1/search/jobs`) : ce serait contourner l'interdit ;
- il **publie** en revanche le plan de ses offres (`/app/job-sitemap*.xml`,
  environ deux mille, datées), sous `/job/…`, que robots.txt autorise ;
- chaque page d'offre charge son contenu depuis `bpce/v1/posts/?_uid=…`, dont
  l'identifiant vient de la table des routes que toute page du site charge
  (`bpce/v1/routes/`). On lit ce que lit la page, pour les seules offres du
  plan publié : un JobPosting (entité, lieu, date) et la description.

Le site Oracle vers lequel pointe le bouton « Postuler » (`ekez…/sites/CX`) ne
liste qu'une trentaine d'offres, la plus récente d'avril : il ne sert pas.
"""

from __future__ import annotations

import re
from datetime import datetime
from html import unescape

from .commun import Annonce, contrat, texte
from .logiciel import Logiciel
from .pays import depuis_nom
from .plan_du_site import _date, titre_de_l_adresse
from .registre import Employeur

BASE = "https://recrutement.bpce.fr"
PLANS = ("/app/job-sitemap1.xml", "/app/job-sitemap2.xml", "/app/job-sitemap3.xml")
_URL = re.compile(r"<url>\s*<loc>\s*([^<\s]+)\s*</loc>\s*(?:<lastmod>\s*([^<\s]+)\s*</lastmod>)?", re.S)


class Bpce(Logiciel):
    cle = "bpce"

    def _routes(self) -> dict[str, str]:
        url = f"{BASE}/app/wp-json/bpce/v1/routes/?lang=fr"
        self.verifier(url)
        r = self.http.get(url, utiliser_cache=False, revalider=True)
        routes = r.json_ if isinstance(r.json_, list) else []
        return {x["path"].rstrip("/"): x["_uid"] for x in routes
                if isinstance(x, dict) and str(x.get("_uid", "")).startswith("job-") and x.get("path")}

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        publiees: dict[str, datetime | None] = {}
        for plan in PLANS:
            self.verifier(f"{BASE}{plan}")
            r = self.http.get(f"{BASE}{plan}", utiliser_cache=False, revalider=True, statuts_acceptes=(200, 404))
            if r.statut != 200:
                break
            for loc, modifie in _URL.findall(r.texte or ""):
                chemin = re.sub(r"^https?://[^/]+", "", loc).rstrip("/")
                if chemin.startswith("/job/"):
                    publiees[chemin] = _date(modifie)
        routes = self._routes()
        annonces = []
        for chemin, modifie in publiees.items():
            if chemin not in routes or (modifie is not None and modifie < depuis):
                continue
            annonces.append(Annonce(
                ident=routes[chemin].split("-")[1], titre=titre_de_l_adresse(chemin, None),
                url=f"{BASE}{chemin}", publiee_le=modifie, brut={"uid": routes[chemin]},
            ))
        annonces.sort(key=lambda a: a.publiee_le or datetime.min, reverse=True)
        return annonces

    def completer(self, employeur: Employeur, annonce: Annonce) -> Annonce:
        self.verifier(annonce.url)
        url = f"{BASE}/app/wp-json/bpce/v1/posts/?lang=fr&_uid={annonce.brut['uid']}"
        self.verifier(url)
        d = self.http.get(url).json_
        contenu = (d or {}).get("content") or {} if isinstance(d, dict) else {}
        offre = contenu.get("microdatas") or {}
        haut = contenu.get("top") or {}
        if not offre and not haut:
            return annonce
        # « ASSISTANT GESTION FINANCIERE &amp; ALM » : le titre arrive échappé en HTML.
        annonce.titre = " ".join(unescape(str(offre.get("title") or haut.get("title") or annonce.titre)).split())
        annonce.description = texte((contenu.get("main") or {}).get("text") or "")
        lieux = haut.get("localisations") or []
        premier = lieux[0] if lieux and isinstance(lieux[0], dict) else {}
        annonce.lieu = premier.get("city") or premier.get("place") or ""
        annonce.pays = depuis_nom(premier.get("country")) or depuis_nom(
            ((offre.get("jobLocation") or [{}])[0].get("address") or {}).get("addressCountry"))
        annonce.entreprise = str((offre.get("hiringOrganization") or {}).get("name")
                                 or (haut.get("criteria") or {}).get("brand") or "")
        annonce.publiee_le = _date(offre.get("datePosted")) or annonce.publiee_le
        annonce.contrat = contrat(annonce.titre)
        annonce.complete = True
        return annonce
