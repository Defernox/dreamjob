"""Scan quotidien automatique.

**DreamJob n'est pas un serveur.** Il tourne quand l'utilisateur l'ouvre, pas
24 h sur 24. Un simple « tous les jours à 7 h 30 » ne suffit donc pas : si
l'application est fermée à cette heure-là, le rendez-vous est manqué et rien ne
le rattrape.

D'où deux déclencheurs complémentaires :

- **l'heure quotidienne**, utile si l'application reste ouverte ;
- **le rattrapage au démarrage**, qui lance un scan peu après l'ouverture si
  aucun n'a abouti depuis un certain nombre d'heures.

Le scan planifié ne fait rien de plus que le scan manuel — mêmes sources, même
déduplication, et toujours aucun appel LLM.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlmodel import Session

from .config import reglages as lire_reglages
from .db import engine
from .models.base import maintenant
from .services.scan import dernier_scan_abouti, lancer_scan, requetes_actives
from .services.scoring import ProfilVide, scorer_toutes

log = logging.getLogger("dreamjob.planificateur")

TACHE_QUOTIDIENNE = "scan_quotidien"
TACHE_RATTRAPAGE = "scan_rattrapage"
# Au-dela, on n'attend plus un scan en cours : fermer l'application doit rester
# une operation rapide.
DELAI_ARRET_SECONDES = 20

_planificateur: BackgroundScheduler | None = None


def executer_scan(declenche_par: str = "planifie") -> None:
    """Scan puis scoring. Aucune exception ne doit remonter : le planificateur
    tournerait sinon en erreur silencieuse jusqu'au prochain redémarrage."""
    try:
        with Session(engine) as session:
            # Toutes les recherches enregistrées, pas seulement config.yaml :
            # le scan automatique doit couvrir exactement ce que l'utilisateur
            # cherche, sinon il travaille plus étroit que lui.
            requetes = requetes_actives(session, lire_reglages())
            scan = lancer_scan(session, requetes, declenche_par=declenche_par)
            log.info("Scan %s : %d nouvelles offres (statut %s, %d recherche(s))",
                     declenche_par, scan.nb_nouvelles, scan.statut, len(requetes))
            try:
                # Sans condition sur les nouveautés : un changement de poids ou
                # de profil laisse des offres à rescorer même sans arrivée.
                # `scorer_toutes` ne traite de toute façon que ce qui le nécessite.
                resultat = scorer_toutes(session)
                if resultat["scorees"]:
                    log.info("Scoring : %d offres", resultat["scorees"])
            except ProfilVide as e:
                log.warning("Offres non scorées — %s", e)
    except Exception:  # noqa: BLE001
        log.exception("Le scan %s a échoué", declenche_par)


def _programmer_rattrapage(planificateur: BackgroundScheduler) -> None:
    r = lire_reglages().planification
    if r.rattrapage_apres_heures <= 0:
        return

    with Session(engine) as session:
        dernier = dernier_scan_abouti(session)

    if dernier is None:
        # Base vierge : la toute premiere recherche revient a l'utilisateur.
        # Sortir sur le reseau avant qu'il ait seulement vu l'ecran Profil
        # serait une initiative qu'il n'a pas demandee.
        log.info("Aucun scan dans l'historique : le premier reste manuel.")
        return

    ecoule = maintenant() - dernier.started_at
    if ecoule < timedelta(hours=r.rattrapage_apres_heures):
        log.info("Dernier scan il y a %s : pas de rattrapage.", _duree_lisible(ecoule))
        return

    # Heure consciente du fuseau DU PLANIFICATEUR : un `datetime.now()` naif
    # serait relu comme une heure de Paris, et se retrouverait dans le passe des
    # que la machine change de fuseau — donc jamais execute.
    quand = datetime.now(planificateur.timezone) + timedelta(
        seconds=r.delai_rattrapage_secondes
    )
    planificateur.add_job(
        executer_scan, DateTrigger(run_date=quand), id=TACHE_RATTRAPAGE,
        kwargs={"declenche_par": "rattrapage"}, replace_existing=True,
    )
    log.info("Aucun scan depuis %s : rattrapage dans %d s.",
             _duree_lisible(ecoule), r.delai_rattrapage_secondes)


def _duree_lisible(ecoule: timedelta) -> str:
    heures = int(ecoule.total_seconds() // 3600)
    return f"{heures} h" if heures else f"{int(ecoule.total_seconds() // 60)} min"


# APScheduler abandonne par defaut une execution en retard de plus d'UNE
# seconde. Sur un poste qui dort la nuit, le rendez-vous quotidien serait donc
# systematiquement perdu : on accepte jusqu'a six heures de retard, et
# `coalesce` garantit qu'un reveil apres plusieurs jours ne declenche qu'un
# seul rattrapage au lieu d'un par jour manque.
TOLERANCE_RETARD_SECONDES = 6 * 3600


def demarrer() -> BackgroundScheduler | None:
    global _planificateur
    # Idempotent : un second appel ne doit pas laisser un planificateur
    # orphelin qui continuerait a declencher des scans en double.
    arreter()

    r = lire_reglages().planification
    if not r.scan_quotidien_actif:
        log.info("Scan quotidien désactivé (config.yaml).")
        return None

    heure, minute = r.heure_minute()
    _planificateur = BackgroundScheduler(
        timezone="Europe/Paris",
        job_defaults={"misfire_grace_time": TOLERANCE_RETARD_SECONDES, "coalesce": True},
    )
    _planificateur.add_job(
        executer_scan, CronTrigger(hour=heure, minute=minute),
        id=TACHE_QUOTIDIENNE, replace_existing=True,
    )
    _planificateur.start()
    log.info("Scan quotidien programmé à %02d:%02d.", heure, minute)

    _programmer_rattrapage(_planificateur)
    return _planificateur


def arreter() -> None:
    """Arrete le planificateur en laissant un scan en cours se terminer.

    `wait=False` rendait la main aussitot : le processus se fermait pendant
    l'ecriture des offres, laissant un ScanRun bloque au statut « en cours ».
    On patiente donc, mais dans un thread demon pour ne jamais figer l'arret de
    l'application si le scan s'eternise.
    """
    global _planificateur
    if _planificateur is None:
        return

    planificateur, _planificateur = _planificateur, None
    fermeture = threading.Thread(target=planificateur.shutdown, kwargs={"wait": True},
                                 daemon=True)
    fermeture.start()
    fermeture.join(timeout=DELAI_ARRET_SECONDES)
    if fermeture.is_alive():
        log.warning("Un scan etait encore en cours : arret sans l'attendre davantage.")


def etat() -> dict:
    """Ce que l'interface affiche : actif, prochaine exécution, dernier scan."""
    r = lire_reglages().planification
    heure, minute = r.heure_minute()

    prochaine = None
    if _planificateur is not None:
        tache = _planificateur.get_job(TACHE_QUOTIDIENNE)
        if tache is not None and tache.next_run_time is not None:
            # Convention de l'API (CLAUDE.md) : de l'UTC naif, jamais une
            # heure locale — le front suffixe systematiquement d'un « Z ».
            prochaine = tache.next_run_time.astimezone(timezone.utc).replace(tzinfo=None)

    with Session(engine) as session:
        dernier = dernier_scan_abouti(session)

    return {
        "actif": r.scan_quotidien_actif and _planificateur is not None,
        "heure": f"{heure:02d}:{minute:02d}",
        "prochaine_execution": prochaine,
        "dernier_scan": dernier.started_at if dernier else None,
        "dernier_scan_nouvelles": dernier.nb_nouvelles if dernier else None,
        "rattrapage_apres_heures": r.rattrapage_apres_heures,
    }
