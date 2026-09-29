"""Une interface JSON décrite dans employeurs.yaml : Optiver, Groupama.

Bien des sites carrières faits maison remplissent leur page avec une petite
interface JSON — celle que le navigateur appelle quand on clique sur « voir
plus ». On l'appelle comme la page l'appelle, avec notre User-Agent, et
seulement si robots.txt ne l'interdit pas. Plutôt qu'un connecteur par site,
un seul, décrit dans employeurs.yaml :

- `api` : l'adresse, avec `{debut}`, `{taille}` ou `{page}` pour la pagination ;
- `methode` (GET par défaut, ou POST) et `corps` : le corps JSON d'un POST, où
  les mêmes marques sont remplacées (« {debut} » seul devient un nombre) ;
- `entetes` : en-têtes à joindre (une clé que le site publie dans sa page) ;
- `taille` : offres par page (50 par défaut) — ce que l'interface rend
  VRAIMENT : Optiver en rend seize quoi qu'on demande, et un décalage calculé
  sur cinquante sauterait trente-quatre offres par page ;
- `liste` : le chemin vers le tableau des offres (« items », « data.results ») ;
- `total` : le chemin vers le nombre total d'offres, s'il est donné ;
- `champs` : où lire l'identifiant, l'intitulé, l'adresse, le lieu, le pays,
  la date, le contrat, la description et l'entité. Chaque valeur est un chemin
  (« location.city ») ou un modèle (« https://www.optiver.com{href} »).

Sans description dans la liste, la fiche est ouverte : par la même interface
si `fiche_api` en donne l'adresse (un modèle, comme les champs) et
`fiche_champs` ce qu'il faut y lire ; sinon la page, lue comme le plan du site
la lit (JobPosting, ou le texte entre les repères `bloc` et `fin_bloc`).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any

from .commun import Annonce, contrat, texte
from .pays import depuis_iso, depuis_lieu, depuis_nom
from .plan_du_site import PlanDuSite, _date
from .registre import Employeur

TAILLE = 50
_MARQUE = re.compile(r"\{([\w.]+)\}")


def chemin(donnees: Any, trajet: str) -> Any:
    """`chemin({"a": {"b": 3}}, "a.b")` → 3 ; un maillon absent rend None."""
    for morceau in (trajet or "").split("."):
        if not morceau:
            continue
        if isinstance(donnees, dict):
            donnees = donnees.get(morceau)
        elif isinstance(donnees, list) and morceau.isdigit() and int(morceau) < len(donnees):
            donnees = donnees[int(morceau)]
        else:
            return None
    return donnees


def valeur(offre: dict, regle: str | list | None) -> str:
    """Un champ de l'offre : un chemin, ou un modèle dont chaque `{chemin}` est
    remplacé. Une liste (plusieurs lieux) est jointe par des virgules ; une
    liste de règles (la description, puis le profil) est jointe ligne à ligne."""
    if not regle:
        return ""
    if isinstance(regle, list):
        return "\n".join(filter(None, (valeur(offre, r) for r in regle)))
    if "{" in regle:
        return _MARQUE.sub(lambda m: valeur(offre, m.group(1)), regle)
    brut = chemin(offre, regle)
    if isinstance(brut, list):
        return ", ".join(str(x) for x in brut if x not in (None, ""))
    return "" if brut is None else str(brut)


_PAGINATION = re.compile(r"\{(debut|taille|page)\}")


def _paginer(texte_: str, marques: dict[str, int]) -> str:
    """Les seules marques de pagination sont remplacées : une accolade d'une
    autre nature (un filtre JSON dans l'adresse) reste telle quelle."""
    return _PAGINATION.sub(lambda m: str(marques[m.group(1)]), texte_)


def _remplir(modele: Any, marques: dict[str, int]) -> Any:
    """Les marques de pagination dans un corps JSON : « {debut} » seul devient
    le nombre, pour que l'interface reçoive un entier et non un texte."""
    if isinstance(modele, dict):
        return {k: _remplir(v, marques) for k, v in modele.items()}
    if isinstance(modele, list):
        return [_remplir(v, marques) for v in modele]
    if isinstance(modele, str):
        if (m := _PAGINATION.fullmatch(modele)) is not None:
            return marques[m.group(1)]
        return _paginer(modele, marques)
    return modele


def _date_de(brut: str) -> datetime | None:
    """ISO (« 2026-09-16T11:59:45Z »), ou un instant Unix en millisecondes."""
    if brut.isdigit() and len(brut) >= 12:
        return datetime.fromtimestamp(int(brut) / 1000, tz=timezone.utc).replace(tzinfo=None)
    return _date(brut)


class ApiJson(PlanDuSite):
    cle = "api_json"

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        o = employeur.options
        taille = int(o.get("taille") or TAILLE)
        champs = o.get("champs") or {}
        vues: dict[str, Annonce] = {}
        vus: set[str] = set()
        for page in range(pages_max):
            marques = {"debut": page * taille, "taille": taille, "page": page + 1}
            url = _paginer(str(o["api"]), marques)
            self.verifier(url)
            entetes = {"Accept": "application/json", **(o.get("entetes") or {})}
            if str(o.get("methode") or "GET").upper() == "POST":
                r = self.http.post(url, corps_json=_remplir(o.get("corps") or {}, marques),
                                   entetes=entetes, utiliser_cache=False)
            else:
                r = self.http.get(url, entetes=entetes, utiliser_cache=False, revalider=True)
            donnees = r.json_ if r.json_ is not None else json.loads(r.texte or "null")
            lot = chemin(donnees, o.get("liste") or "")
            if not isinstance(lot, list) or not lot:
                break
            # Une page qui n'apporte rien de neuf clôt la lecture : Optiver
            # plafonne sa page à seize offres quoi qu'on demande, et une
            # interface qui ignore la pagination renverrait la même liste.
            neuves = 0
            for offre in lot:
                if not isinstance(offre, dict):
                    continue
                cle = valeur(offre, champs.get("ident")) or valeur(offre, champs.get("url"))
                if cle in vus:
                    continue
                vus.add(cle)
                neuves += 1
                if a := self._annonce(offre, champs, pays, depuis):
                    if o.get("fiche_api"):
                        a.brut["fiche_api"] = valeur(offre, o["fiche_api"])
                    # Une fiche déclarée (`bloc`, `fiche_api`) est toujours lue :
                    # la liste de Groupama n'en donne qu'un résumé automatique.
                    if o.get("bloc") or o.get("fiche_api"):
                        a.complete = False
                    vues.setdefault(a.ident, a)
            total = chemin(donnees, o["total"]) if o.get("total") else None
            if not neuves or (isinstance(total, int) and len(vus) >= total):
                break
        return sorted(vues.values(), key=lambda a: a.publiee_le or datetime.min, reverse=True)

    @staticmethod
    def _annonce(offre: dict, champs: dict, pays: list[str], depuis: datetime) -> Annonce | None:
        titre = " ".join(unescape(valeur(offre, champs.get("titre"))).split())
        url = valeur(offre, champs.get("url"))
        ident = valeur(offre, champs.get("ident")) or url
        if not titre or not ident:
            return None
        publiee = _date_de(valeur(offre, champs.get("date")))
        if publiee is not None and publiee < depuis:
            return None
        lieu = valeur(offre, champs.get("lieu"))
        pays_brut = valeur(offre, champs.get("pays"))
        pays_ = ((depuis_iso(pays_brut) if len(pays_brut) == 2 else depuis_nom(pays_brut))
                 or depuis_lieu(lieu))
        if pays and pays_ and pays_ not in pays:
            return None
        description = texte(valeur(offre, champs.get("description")))
        return Annonce(
            ident=ident, titre=titre, url=url, lieu=lieu, pays=pays_, publiee_le=publiee,
            contrat=contrat(titre, valeur(offre, champs.get("contrat"))),
            description=description, entreprise=valeur(offre, champs.get("entreprise")),
            # Une description courte (un résumé) ne dispense pas d'ouvrir la fiche.
            complete=len(description) >= 400,
        )

    def completer(self, employeur: Employeur, annonce: Annonce) -> Annonce:
        if annonce.complete or not annonce.url:
            annonce.complete = True
            return annonce
        # Lue, pas retirée : si la fiche échoue, la recherche suivante du même
        # scan la redemande à l'interface, pas à la page — une coquille vide.
        if fiche_api := annonce.brut.get("fiche_api"):
            return self._fiche_json(employeur, annonce, fiche_api)
        resume, titre = annonce.description, annonce.titre
        fiche = super().completer(employeur, annonce)
        # L'intitulé de l'interface fait foi : sans balisage, la page n'offre
        # que son titre générique (« Détails offre - Groupama Gan Recrute »).
        if not employeur.options.get("titre_motif"):
            fiche.titre = titre
        fiche.description = fiche.description or resume
        return fiche

    def _fiche_json(self, employeur: Employeur, annonce: Annonce, url: str) -> Annonce:
        """La fiche servie par la même interface (Digital Recruiters : la page
        de l'offre n'est qu'une coquille remplie par script), lue selon
        `fiche_champs` — mêmes règles que `champs`."""
        self.verifier(url)
        r = self.http.get(url, entetes={"Accept": "application/json",
                                        **(employeur.options.get("entetes") or {})})
        fiche = r.json_ if isinstance(r.json_, dict) else {}
        regles = employeur.options.get("fiche_champs") or {}
        annonce.description = texte(valeur(fiche, regles.get("description"))) or annonce.description
        annonce.publiee_le = _date_de(valeur(fiche, regles.get("date"))) or annonce.publiee_le
        annonce.lieu = valeur(fiche, regles.get("lieu")) or annonce.lieu
        pays_brut = valeur(fiche, regles.get("pays"))
        annonce.pays = ((depuis_iso(pays_brut) if len(pays_brut) == 2 else depuis_nom(pays_brut))
                        or annonce.pays or depuis_lieu(annonce.lieu))
        annonce.contrat = contrat(annonce.titre, valeur(fiche, regles.get("contrat"))) or annonce.contrat
        annonce.complete = True
        return annonce
