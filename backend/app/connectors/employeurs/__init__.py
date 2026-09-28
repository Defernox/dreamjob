"""Les sites carrières des employeurs : les offres à la source, avant tout le monde.

Une banque publie d'abord sur son propre site ; les agrégateurs reprennent
l'annonce des jours plus tard, parfois jamais, et Adzuna la tronque à 500
caractères. Avant cette source, la base comptait douze offres de BNP Paribas et
dix de Société Générale — des groupes qui en ont des centaines d'ouvertes.

**Un connecteur par logiciel, pas par employeur.** Les sites carrières reposent
sur une poignée de logiciels (Workday, SuccessFactors, Talentsoft, Oracle…) ;
ajouter un employeur, c'est une ligne dans `employeurs.yaml`.

**On ne demande pas aux sites de chercher.** Chaque employeur est listé une fois
par scan, filtré sur les pays voulus, du plus récent au plus ancien jusqu'à la
fenêtre de dates ; les intitulés sont comparés ensuite, ici, avec le vocabulaire
du score (`commun.correspond`). Une fiche n'est ouverte que pour une offre
nouvelle qui répond à une recherche : celles déjà en base sont seulement
signalées « toujours en ligne ».

**Mêmes règles que partout** : robots.txt relu à chaque scan, une requête par
seconde et par site, notre User-Agent et rien d'autre. Un site protégé contre
les robots est refusé, jamais contourné — le motif est consigné dans
`employeurs.yaml`. Un employeur en panne n'arrête pas les autres.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from ...config import RACINE
from ...models.base import maintenant
from ..base import BaseConnector, ErreurConnecteur, RawOffer, SearchQuery
from ..http import ErreurHttp
from .commun import Annonce, Interdit, correspond, identifiant
from .commun import cles as cles_de
from .logiciel import Logiciel
from .registre import ACTIF, Employeur, charger
from .robots import Robots
from .bpce import Bpce
from .eightfold import Eightfold
from .greenhouse import Greenhouse
from .jibe import Jibe
from .oracle import Oracle
from .plan_du_site import PlanDuSite
from .successfactors import SuccessFactors
from .talentsoft import Talentsoft
from .workday import Workday

log = logging.getLogger("dreamjob.employeurs")

LOGICIELS: dict[str, type[Logiciel]] = {
    Workday.cle: Workday,
    Talentsoft.cle: Talentsoft,
    SuccessFactors.cle: SuccessFactors,
    Oracle.cle: Oracle,
    Greenhouse.cle: Greenhouse,
    PlanDuSite.cle: PlanDuSite,
    Bpce.cle: Bpce,
    Eightfold.cle: Eightfold,
    Jibe.cle: Jibe,
}

# Les contrats qu'une annonce d'employeur ne prend pas la peine d'écrire.
CONTRATS_ORDINAIRES = {"CDI", "CDD"}


class EmployeursConnector(BaseConnector):
    cle = "employeurs"
    libelle = "Sites des employeurs"
    # Le scan lui confie les identifiants déjà en base : ces offres-là n'ont pas
    # besoin que leur fiche soit rouverte.
    veut_les_connus = True

    def __init__(self, http, reglages) -> None:
        super().__init__(http, reglages)
        self.connus: set[str] = set()
        self.pannes: dict[str, str] = {}
        self._robots = Robots(http, reglages.user_agent)
        self._logiciels = {cle: classe(http, self._robots) for cle, classe in LOGICIELS.items()}
        self._listes: dict[tuple, list[tuple[Employeur, Annonce]]] = {}
        self._fiches: dict[str, Annonce] = {}

    # ---------------------------------------------------------------- employeurs

    def employeurs(self) -> list[Employeur]:
        chemin = RACINE / self.reglages.employeurs.fichier
        return [e for e in charger(chemin)
                if e.statut == ACTIF and e.logiciel in self._logiciels and e.adresse]

    def _lister(self, employeurs: list[Employeur], pays: list[str],
                depuis: datetime) -> list[tuple[Employeur, Annonce]]:
        """Toutes les annonces récentes de tous les employeurs, une fois par
        scan et par fenêtre : les recherches suivantes trient la même liste."""
        cle = (tuple(pays), depuis.date())
        if cle in self._listes:
            return self._listes[cle]
        pages = self.reglages.employeurs.pages_max

        def un(e: Employeur) -> list[tuple[Employeur, Annonce]]:
            try:
                return [(e, a) for a in self._logiciels[e.logiciel].annonces(e, pays, depuis, pages)]
            except Interdit as ex:
                self.pannes[e.nom] = str(ex)
                log.warning("%s : %s", e.nom, ex)
            except ErreurHttp as ex:
                self.pannes[e.nom] = f"{type(ex).__name__}: {ex}"
                log.warning("%s : liste illisible — %s", e.nom, ex)
            except Exception as ex:  # noqa: BLE001 — un site qui change de format n'arrête pas les autres
                self.pannes[e.nom] = f"{type(ex).__name__}: {ex}"
                log.exception("%s : liste illisible", e.nom)
            return []

        with ThreadPoolExecutor(max_workers=self.reglages.employeurs.en_parallele) as pool:
            toutes = [paire for liste in pool.map(un, employeurs) for paire in liste]
        log.info("%d employeurs listés, %d annonces récentes, %d en panne",
                 len(employeurs), len(toutes), len(self.pannes))
        self._listes[cle] = toutes
        return toutes

    def _completer(self, paires: list[tuple[Employeur, Annonce]]) -> None:
        a_ouvrir = [(e, a) for e, a in paires if self._id(e, a) not in self._fiches]

        def un(paire: tuple[Employeur, Annonce]) -> None:
            e, a = paire
            try:
                fiche = self._logiciels[e.logiciel].completer(e, a)
                # Arkéa ne donne que la ville (« Brest ») : pour un employeur dont
                # tous les postes sont dans un pays, employeurs.yaml le dit.
                fiche.pays = fiche.pays or e.options.get("pays_par_defaut", "")
                self._fiches[self._id(e, a)] = fiche
            except (Interdit, ErreurHttp) as ex:
                log.warning("%s : fiche illisible (%s) — %s", e.nom, a.url, ex)
            except Exception:  # noqa: BLE001 — une fiche au format imprévu n'arrête pas les autres
                log.exception("%s : fiche illisible (%s)", e.nom, a.url)

        with ThreadPoolExecutor(max_workers=self.reglages.employeurs.en_parallele) as pool:
            list(pool.map(un, a_ouvrir))

    # --------------------------------------------------------------------- scan

    @staticmethod
    def _id(employeur: Employeur, annonce: Annonce) -> str:
        return f"{identifiant(employeur.nom)}:{annonce.ident}"

    def fetch(self, query: SearchQuery) -> list[RawOffer]:
        recherches = cles_de(query)
        employeurs = self.employeurs()
        if not recherches or not employeurs:
            return []
        jours = query.publiee_depuis_jours or self.reglages.employeurs.fenetre_jours
        depuis = maintenant() - timedelta(days=jours)
        annonces = self._lister(employeurs, sorted(query.pays), depuis)
        if len(self.pannes) == len(employeurs):
            raise ErreurConnecteur(f"aucun site d'employeur n'a répondu ({len(employeurs)} essayés)")

        retenues = [(e, a) for e, a in annonces
                    if correspond(a.titre, recherches) and self._acceptee(a, query)]
        nouvelles = [(e, a) for e, a in retenues if self._id(e, a) not in self.connus]
        # Au-delà du plafond, les plus récentes d'abord : ce sont elles qu'on
        # risque de voir partir.
        nouvelles.sort(key=lambda p: p[1].publiee_le or datetime.min, reverse=True)
        nouvelles = nouvelles[:query.max_offres]
        self._completer(nouvelles)

        gardees = {self._id(e, a) for e, a in nouvelles}
        brutes = []
        for e, a in retenues:
            ident = self._id(e, a)
            if ident in self.connus:
                brutes.append(self._brute(e, a, ident))
            elif ident in gardees and ident in self._fiches:
                fiche = self._fiches[ident]
                # La fiche dit le vrai pays : « 3 Locations » en liste peut
                # cacher un poste en Inde.
                if self._acceptee(fiche, query):
                    brutes.append(self._brute(e, fiche, ident))
        return brutes

    @staticmethod
    def _acceptee(annonce: Annonce, query: SearchQuery) -> bool:
        if query.pays and annonce.pays and annonce.pays not in query.pays:
            return False
        # Une recherche réservée aux contrats particuliers (V.I.E, stage…) veut
        # les voir écrits. Sur un site d'employeur, un contrat que l'annonce ne
        # précise pas est un CDI ou un CDD, presque jamais un V.I.E : le laisser
        # passer versait tous les postes « finance » dans la recherche V.I.E.
        if query.contrats and not set(query.contrats) & CONTRATS_ORDINAIRES:
            return annonce.contrat in query.contrats
        return True

    def _brute(self, employeur: Employeur, annonce: Annonce, ident: str) -> RawOffer:
        return RawOffer(
            source=self.cle,
            source_id=ident,
            titre=annonce.titre,
            url=annonce.url,
            entreprise=annonce.entreprise or employeur.nom,
            lieu=annonce.lieu,
            pays=annonce.pays,
            type_contrat=annonce.contrat,
            date_publication=annonce.publiee_le,
            description_brute=annonce.description,
            raw={"employeur": employeur.nom, "logiciel": employeur.logiciel,
                 "categorie": employeur.categorie, **annonce.brut},
        )
