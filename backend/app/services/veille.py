"""La veille : repérer une offre dans l'heure où elle paraît, et alerter.

Le scan quotidien trouve une offre le lendemain au mieux. Mesuré sur la base
locale, où l'application n'était ouverte que de temps en temps, le retard
médian entre la publication d'une offre et sa découverte était de **6,6 jours**
chez France Travail, 12,8 chez Civiweb. Arriver parmi les premiers compte : un
recruteur trie souvent au fil de l'eau et ferme l'annonce dès qu'il a de quoi
faire.

La veille joue donc, toutes les `intervalle_minutes` en journée, une recherche
légère — **les seules offres du jour** — sur les sources qui le permettent, note
les nouvelles et alerte aussitôt pour les vertes (`notification.alerter`).

**On ratisse large.** Quand il ne s'agit que de repérer les nouveautés, une
requête de plus ne coûte presque rien et le score trie derrière : aux recherches
enregistrées s'ajoutent les intitulés tirés du CV — titre visé, postes occupés,
mots-clés des expériences, secteurs visés.

**Toutes les sources n'y entrent pas.** Adzuna plafonne à 250 appels par jour et
2 500 par mois, et le scan quotidien en consomme déjà les trois cinquièmes ; il
reprend d'ailleurs des annonces publiées ailleurs, souvent avec plusieurs jours
de retard. DogFinance est limité à quarante pages par jour, pour une raison
juridique. Les deux restent au scan du matin.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from sqlmodel import Session, delete, select

from ..config import Reglages
from ..connectors.base import SearchQuery
from ..models import Profile, ScanRun, Utilisateur
from ..models.base import maintenant
from ..scoring.cible import construire
from ..scoring.texte import normaliser
from .scan import Demande, lancer_scan, requete_depuis_profil, requetes_actives

log = logging.getLogger("dreamjob.veille")

DECLENCHEUR = "veille"
# Les intitulés du CV qui disent un métier. Pas les diplômes : « Master 2 PGE
# Finance » n'est pas un poste qu'on cherche.
ORIGINES_RETENUES = ("titre visé", "poste", "thème", "secteur")
_PONCTUATION = re.compile(r"[^\w\s'’-]+", re.UNICODE)


def _du_jour(requete: SearchQuery, reglages: Reglages) -> SearchQuery:
    """La même recherche, limitée aux offres publiées depuis la veille."""
    return SearchQuery(
        mots_cles=list(requete.mots_cles),
        pays=list(requete.pays),
        contrats=list(requete.contrats),
        departement=requete.departement,
        publiee_depuis_jours=1,
        max_offres=min(requete.max_offres, reglages.veille.max_offres_par_requete),
    )


def _intitules_du_cv(session: Session, reglages: Reglages, utilisateur_id: int,
                     deja: set[str]) -> list[SearchQuery]:
    """Des requêtes de plus, tirées du CV : les intitulés qui disent un métier,
    du plus fort au plus faible, sans répéter une recherche enregistrée."""
    profil = session.exec(
        select(Profile).where(Profile.utilisateur_id == utilisateur_id)).first()
    if profil is None:
        return []
    repli = requete_depuis_profil(session, reglages, utilisateur_id)
    intitules = sorted(
        (i for i in construire(profil, []).intitules
         if i.origine.startswith(ORIGINES_RETENUES)),
        key=lambda i: -i.poids)
    requetes: list[SearchQuery] = []
    for intitule in intitules:
        libelle = " ".join(_PONCTUATION.sub(" ", intitule.libelle).split())
        cle = normaliser(libelle)
        if not cle or cle in deja:
            continue
        deja.add(cle)
        requetes.append(SearchQuery(
            mots_cles=[libelle], pays=repli.pays, contrats=repli.contrats,
            publiee_depuis_jours=1, max_offres=reglages.veille.max_offres_par_requete,
        ))
        if len(requetes) >= reglages.veille.requetes_du_cv_max:
            break
    return requetes


def demandes_de_veille(session: Session, reglages: Reglages) -> list[Demande]:
    """Ce que la veille joue, pour chaque compte : ses recherches enregistrées,
    limitées aux offres du jour, puis les intitulés tirés de son CV."""
    demandes: list[Demande] = []
    for utilisateur in session.exec(select(Utilisateur).order_by(Utilisateur.id)).all():
        recherches = requetes_actives(session, reglages, utilisateur.id)
        deja = {normaliser(" ".join(r.mots_cles)) for r in recherches}
        requetes = [_du_jour(r, reglages) for r in recherches]
        if reglages.veille.elargir_depuis_le_cv:
            requetes += _intitules_du_cv(session, reglages, utilisateur.id, deja)
        demandes += [Demande(utilisateur.id, r) for r in requetes]
    return demandes


def dans_la_plage(reglages: Reglages, heure: int) -> bool:
    return reglages.veille.heure_debut <= heure < reglages.veille.heure_fin


def faire_le_menage(session: Session, reglages: Reglages) -> int:
    """Oublie les veilles de plus de `conserver_jours` : trente par jour
    noieraient l'historique des scans. Les offres trouvées, elles, restent."""
    limite = maintenant() - timedelta(days=reglages.veille.conserver_jours)
    resultat = session.exec(delete(ScanRun).where(
        ScanRun.declenche_par == DECLENCHEUR, ScanRun.started_at < limite))
    session.commit()
    return resultat.rowcount or 0


def veiller(session: Session, reglages: Reglages) -> ScanRun | None:
    """Une passe de veille : chercher, noter, alerter. Renvoie le scan, ou None
    s'il n'y avait rien à chercher."""
    from .notification import alerter
    from .scoring import scorer_tous_les_comptes

    demandes = demandes_de_veille(session, reglages)
    if not demandes:
        return None
    sources = [s for s in reglages.veille.sources
               if s in reglages.sources and reglages.sources[s].actif]
    scan = lancer_scan(session, demandes, sources=sources, declenche_par=DECLENCHEUR)
    log.info("Veille : %d requête(s), %d nouvelle(s) offre(s)", len(demandes), scan.nb_nouvelles)
    # Toujours, et pas seulement s'il y a du neuf : une offre déjà en base peut
    # entrer dans le fil d'un compte qu'elle n'intéressait pas encore.
    scorer_tous_les_comptes(session)
    alerter(session, depuis=scan.started_at)
    faire_le_menage(session, reglages)
    return scan
