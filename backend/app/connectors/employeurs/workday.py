"""Workday : Bank of America, Barclays, Citi, State Street, Rothschild & Co…

Chaque site carrières Workday (`<locataire>.wdN.myworkdayjobs.com/<site>`)
s'alimente à une interface JSON publique, celle que la page elle-même
interroge : `POST /wday/cxs/<locataire>/<site>/jobs` pour la liste, `GET` sur le
chemin de l'offre pour la fiche. Vérifié le 2026-09-28 :

- `robots.txt` de chaque locataire autorise le site et n'interdit que
  `/refreshFacet/` ; il publie un plan du site, mais limité à cent offres —
  la liste est donc la seule voie complète ;
- sans mot-clé, la liste est triée de la plus récente à la plus ancienne :
  la veille ne lit que la première page ;
- le filtre par pays (`Location_Country`, parfois imbriqué sous
  `locationMainGroup`) accepte plusieurs pays d'un coup ;
- la date n'y est que relative (« Posted 3 Days Ago », « 30+ Days ») ; la fiche
  donne la date exacte et le pays en code ISO.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

from ...models.base import maintenant
from .commun import Annonce, contrat, texte
from .logiciel import Logiciel
from .pays import depuis_iso, depuis_lieu, depuis_nom
from .registre import Employeur

PAR_PAGE = 20
ENTETES = {"Accept": "application/json", "Accept-Language": "en-US"}
_LOCALE = re.compile(r"^[a-z]{2}-[A-Z]{2}$", re.I)
_IL_Y_A = re.compile(r"(\d+)\+?\s+days?", re.I)


def adresses(employeur: Employeur) -> tuple[str, str]:
    """(racine de l'interface, racine publique) d'après l'adresse du site :
    `https://statestreet.wd1.myworkdayjobs.com/en-US/Global` donne l'interface
    `…/wday/cxs/statestreet/Global` et les offres sous `…/Global`."""
    p = urlparse(employeur.adresse)
    locataire = employeur.options.get("locataire") or p.netloc.split(".")[0]
    segments = [s for s in p.path.split("/") if s and not _LOCALE.match(s)]
    if not segments:
        raise ValueError(f"Adresse Workday sans site : {employeur.adresse}")
    site = segments[0]
    return (f"https://{p.netloc}/wday/cxs/{locataire}/{site}", f"https://{p.netloc}/{site}")


def jours(texte_relatif: str | None) -> int | None:
    """« Posted Today » → 0, « Yesterday » → 1, « 3 Days Ago » → 3,
    « 30+ Days Ago » → 31. Illisible → None : on ne jette rien sur une date
    qu'on ne sait pas lire."""
    t = (texte_relatif or "").lower()
    if "today" in t:
        return 0
    if "yesterday" in t:
        return 1
    if m := _IL_Y_A.search(t):
        return int(m.group(1)) + (1 if "+" in t else 0)
    return None


def _facettes_pays(facettes: list, voulus: list[str]) -> tuple[str, list[str]] | None:
    """(paramètre, identifiants) du filtre par pays, ou None si le site n'en a
    pas. Le filtre peut être imbriqué sous un groupe de lieux."""
    for f in facettes or []:
        parametre = f.get("facetParameter") or ""
        valeurs = f.get("values") or []
        if "country" in parametre.lower() and valeurs and "id" in valeurs[0]:
            ids = [v["id"] for v in valeurs if depuis_nom(v.get("descriptor")) in voulus]
            return parametre, ids
        imbrique = _facettes_pays([v for v in valeurs if "facetParameter" in v], voulus)
        if imbrique is not None:
            return imbrique
    return None


class Workday(Logiciel):
    cle = "workday"

    def _page(self, api: str, filtres: dict, debut: int, taille: int) -> dict:
        r = self.http.post(f"{api}/jobs", corps_json={
            "appliedFacets": filtres, "limit": taille, "offset": debut, "searchText": "",
        }, entetes=ENTETES, utiliser_cache=False)
        return r.json_ if isinstance(r.json_, dict) else {}

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        api, public = adresses(employeur)
        self.verifier(f"{api}/jobs")
        filtres: dict = {}
        if pays:
            trouve = _facettes_pays(self._page(api, {}, 0, 1).get("facets"), pays)
            if trouve is not None:
                parametre, ids = trouve
                if not ids:
                    return []          # aucune offre dans les pays voulus
                filtres = {parametre: ids}

        maintenant_ = maintenant()
        annonces: list[Annonce] = []
        total = None
        for page in range(pages_max):
            d = self._page(api, filtres, page * PAR_PAGE, PAR_PAGE)
            # Le total n'est donné qu'avec la première page ; les suivantes
            # répondent 0.
            total = d.get("total") if total is None else total
            offres = d.get("jobPostings") or []
            trop_vieille = False
            for j in offres:
                age = jours(j.get("postedOn"))
                publiee = maintenant_ - timedelta(days=age) if age is not None else None
                if publiee is not None and publiee < depuis:
                    trop_vieille = True
                    break
                chemin = j.get("externalPath") or ""
                if not chemin or not j.get("title"):
                    continue
                lieu = j.get("locationsText") or ""
                annonces.append(Annonce(
                    ident=chemin.rstrip("/").rsplit("/", 1)[-1],
                    titre=j["title"].strip(),
                    url=f"{public}{chemin}",
                    lieu=lieu,
                    pays=depuis_lieu(lieu),
                    publiee_le=publiee,
                    contrat=contrat(j["title"]),
                    brut={"chemin": chemin},
                ))
            if trop_vieille or not offres or (total and (page + 1) * PAR_PAGE >= total):
                break
        return annonces

    def completer(self, employeur: Employeur, annonce: Annonce) -> Annonce:
        api, _ = adresses(employeur)
        url = f"{api}{annonce.brut['chemin']}"
        self.verifier(url)
        r = self.http.get(url, entetes=ENTETES)
        info = (r.json_ or {}).get("jobPostingInfo") or {} if isinstance(r.json_, dict) else {}
        if not info:
            return annonce
        lieu_structure = info.get("jobRequisitionLocation") or {}
        pays_structure = lieu_structure.get("country") or info.get("country") or {}
        annonce.description = texte(info.get("jobDescription"))
        annonce.lieu = info.get("location") or annonce.lieu
        annonce.pays = (depuis_iso(pays_structure.get("alpha2Code"))
                        or depuis_nom(pays_structure.get("descriptor"))
                        or depuis_lieu(annonce.lieu) or annonce.pays)
        if debut := info.get("startDate"):
            try:
                annonce.publiee_le = datetime.fromisoformat(debut[:10])
            except ValueError:
                pass
        # L'intitulé et le type de poste, pas la description : « internship »
        # ou « permanent » y apparaissent dans bien d'autres sens.
        annonce.contrat = contrat(annonce.titre, info.get("timeType") or "") or annonce.contrat
        annonce.url = info.get("externalUrl") or annonce.url
        annonce.brut["date_limite"] = info.get("endDate")
        annonce.complete = True
        return annonce
