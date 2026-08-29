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
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlmodel import Session, desc, select

from .config import reglages as lire_reglages
from .db import engine
from .models import ScanRun
from .models.base import maintenant
from .models.enums import StatutScan
from .services.scan import lancer_scan
from .services.scoring import ProfilVide, scorer_toutes

log = logging.getLogger("dreamjob.planificateur")

TACHE_QUOTIDIENNE = "scan_quotidien"
TACHE_RATTRAPAGE = "scan_rattrapage"

_planificateur: BackgroundScheduler | None = None


def dernier_scan_abouti(session: Session) -> ScanRun | None:
    """Le dernier scan qui a réellement ramené quelque chose.

    Un scan en échec ne compte pas : sinon une panne de source ferait croire que
    la veille est à jour.
    """
    return session.exec(
        select(ScanRun)
        .where(ScanRun.statut.in_([StatutScan.TERMINE.value, StatutScan.PARTIEL.value]))
        .order_by(desc(ScanRun.started_at))
        .limit(1)
    ).first()


def executer_scan(declenche_par: str = "planifie") -> None:
    """Scan puis scoring. Aucune exception ne doit remonter : le planificateur
    tournerait sinon en erreur silencieuse jusqu'au prochain redémarrage."""
    try:
        with Session(engine) as session:
            scan = lancer_scan(session, declenche_par=declenche_par)
            log.info("Scan %s : %d nouvelles offres (statut %s)",
                     declenche_par, scan.nb_nouvelles, scan.statut)
            if scan.nb_nouvelles:
                try:
                    resultat = scorer_toutes(session)
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

    ecoule = (maintenant() - dernier.started_at) if dernier else None
    if ecoule is not None and ecoule < timedelta(hours=r.rattrapage_apres_heures):
        log.info("Dernier scan il y a %s : pas de rattrapage.", _duree_lisible(ecoule))
        return

    quand = datetime.now() + timedelta(seconds=r.delai_rattrapage_secondes)
    planificateur.add_job(
        executer_scan, DateTrigger(run_date=quand), id=TACHE_RATTRAPAGE,
        kwargs={"declenche_par": "rattrapage"}, replace_existing=True,
    )
    log.info("Aucun scan depuis %s : rattrapage dans %d s.",
             _duree_lisible(ecoule) if ecoule else "toujours",
             r.delai_rattrapage_secondes)


def _duree_lisible(ecoule: timedelta) -> str:
    heures = int(ecoule.total_seconds() // 3600)
    return f"{heures} h" if heures else f"{int(ecoule.total_seconds() // 60)} min"


def demarrer() -> BackgroundScheduler | None:
    global _planificateur
    r = lire_reglages().planification
    if not r.scan_quotidien_actif:
        log.info("Scan quotidien désactivé (config.yaml).")
        return None

    heure, minute = r.heure_minute()
    _planificateur = BackgroundScheduler(timezone="Europe/Paris")
    _planificateur.add_job(
        executer_scan, CronTrigger(hour=heure, minute=minute),
        id=TACHE_QUOTIDIENNE, replace_existing=True,
    )
    _planificateur.start()
    log.info("Scan quotidien programmé à %02d:%02d.", heure, minute)

    _programmer_rattrapage(_planificateur)
    return _planificateur


def arreter() -> None:
    global _planificateur
    if _planificateur is not None:
        _planificateur.shutdown(wait=False)
        _planificateur = None


def etat() -> dict:
    """Ce que l'interface affiche : actif, prochaine exécution, dernier scan."""
    r = lire_reglages().planification
    heure, minute = r.heure_minute()

    prochaine = None
    if _planificateur is not None:
        tache = _planificateur.get_job(TACHE_QUOTIDIENNE)
        if tache is not None and tache.next_run_time is not None:
            prochaine = tache.next_run_time.replace(tzinfo=None)

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
