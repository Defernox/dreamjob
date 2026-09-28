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
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func
from sqlmodel import Session, select

from .config import reglages as lire_reglages
from .db import engine
from .models import ScanRun, ScoreOffre
from .models.base import maintenant
from .services.scan import demandes_de_tous, dernier_scan_abouti, lancer_scan
from .services.scoring import scorer_tous_les_comptes
from .services.notification import notifier
from .services.veille import DECLENCHEUR as VEILLE
from .services.veille import dans_la_plage, veiller

log = logging.getLogger("dreamjob.planificateur")

TACHE_QUOTIDIENNE = "scan_quotidien"
TACHE_RATTRAPAGE = "scan_rattrapage"
TACHE_RESCORING = "rescoring_demarrage"
# Au-dela, on n'attend plus un scan en cours : fermer l'application doit rester
# une operation rapide.
DELAI_ARRET_SECONDES = 20

_planificateur: BackgroundScheduler | None = None

FUSEAU = "Europe/Paris"
TACHE_VEILLE = "veille"
# Un scan et une veille ne tournent jamais ensemble : ils écriraient les mêmes
# offres en même temps. Le scan attend ; la veille, elle, passe son tour — une
# demi-heure plus tard, elle reprendra ce que le scan n'aura pas déjà trouvé.
_VERROU_SCAN = threading.Lock()
# Le résumé du matin reprend tout ce qui est vert et n'a pas encore été signalé
# sur ce délai : les nouveautés de la nuit, et celles de la veille au-delà du
# plafond d'alertes du jour.
FENETRE_RESUME = timedelta(days=1)


def executer_scan(declenche_par: str = "planifie") -> None:
    """Scan puis scoring. Aucune exception ne doit remonter : le planificateur
    tournerait sinon en erreur silencieuse jusqu'au prochain redémarrage."""
    with _VERROU_SCAN:
        _executer_scan(declenche_par)


def _executer_scan(declenche_par: str) -> None:
    try:
        with Session(engine) as session:
            # Les recherches enregistrées de CHAQUE compte, pas seulement
            # config.yaml : le scan automatique doit couvrir exactement ce que
            # chacun cherche. Un seul scan pour tous — une annonce demandée par
            # deux comptes n'est téléchargée qu'une fois.
            demandes = demandes_de_tous(session, lire_reglages())
            if not demandes:
                log.info("Scan %s : aucune recherche à jouer.", declenche_par)
                return
            scan = lancer_scan(session, demandes, declenche_par=declenche_par)
            log.info("Scan %s : %d nouvelles offres (statut %s, %d recherche(s))",
                     declenche_par, scan.nb_nouvelles, scan.statut, len(demandes))
            # Sans condition sur les nouveautés : un changement de poids ou
            # de profil laisse des offres à rescorer même sans arrivée.
            # `scorer_toutes` ne traite de toute façon que ce qui le nécessite.
            scorees = scorer_tous_les_comptes(session)
            if scorees:
                log.info("Scoring : %d offres", scorees)
            # Après le scoring : on ne signale que ce qui est noté. Un compte
            # sans sujet ntfy ne reçoit rien.
            notifier(session, depuis=min(scan.started_at, maintenant() - FENETRE_RESUME))
    except Exception:  # noqa: BLE001
        log.exception("Le scan %s a échoué", declenche_par)


def executer_veille() -> None:
    """Une passe de veille, si l'on est dans la plage horaire et qu'aucun scan
    ne tourne. Ne lève jamais."""
    r = lire_reglages()
    heure = datetime.now(_planificateur.timezone if _planificateur else ZoneInfo(FUSEAU)).hour
    if not r.veille.active or not dans_la_plage(r, heure):
        return
    if not _VERROU_SCAN.acquire(blocking=False):
        log.info("Veille sautée : un scan est en cours.")
        return
    try:
        with Session(engine) as session:
            veiller(session, r)
    except Exception:  # noqa: BLE001
        log.exception("La veille a échoué")
    finally:
        _VERROU_SCAN.release()


def _programmer_rattrapage(planificateur: BackgroundScheduler) -> bool:
    """Programme un scan de rattrapage si la veille n'est plus à jour. Vrai s'il
    en a programmé un."""
    r = lire_reglages().planification
    if r.rattrapage_apres_heures <= 0:
        return False

    with Session(engine) as session:
        dernier = dernier_scan_abouti(session)

    if dernier is None:
        # Base vierge : la toute premiere recherche revient a l'utilisateur.
        # Sortir sur le reseau avant qu'il ait seulement vu l'ecran Profil
        # serait une initiative qu'il n'a pas demandee.
        log.info("Aucun scan dans l'historique : le premier reste manuel.")
        return False

    ecoule = maintenant() - dernier.started_at
    if ecoule < timedelta(hours=r.rattrapage_apres_heures):
        log.info("Dernier scan il y a %s : pas de rattrapage.", _duree_lisible(ecoule))
        return False

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
    return True


# Quelques secondes après l'ouverture : l'API répond d'abord.
DELAI_RESCORING_SECONDES = 5


def rescorer_tout() -> None:
    """Remet à jour les notes de tous les comptes — seulement celles qui le
    demandent (version des poids ou des signaux changée, note de la veille).

    Sans lui, une mise à jour du score laissait les anciennes notes à l'écran
    jusqu'au scan suivant, le lendemain. Ne lève jamais.
    """
    try:
        with Session(engine) as session:
            nombre = scorer_tous_les_comptes(session)
        if nombre:
            log.info("Notes remises à jour au démarrage : %d offres.", nombre)
    except Exception:  # noqa: BLE001
        log.exception("Remise à jour des notes au démarrage en échec")


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
        timezone=FUSEAU,
        job_defaults={"misfire_grace_time": TOLERANCE_RETARD_SECONDES, "coalesce": True},
    )
    _planificateur.add_job(
        executer_scan, CronTrigger(hour=heure, minute=minute),
        id=TACHE_QUOTIDIENNE, replace_existing=True,
    )
    veille = lire_reglages().veille
    if veille.active:
        _planificateur.add_job(
            executer_veille,
            IntervalTrigger(minutes=veille.intervalle_minutes,
                            start_date=datetime.now(ZoneInfo(FUSEAU)) + timedelta(minutes=1)),
            id=TACHE_VEILLE, replace_existing=True,
        )
    _planificateur.start()
    log.info("Scan quotidien programmé à %02d:%02d.", heure, minute)
    if veille.active:
        log.info("Veille toutes les %d min, de %d h à %d h.", veille.intervalle_minutes,
                 veille.heure_debut, veille.heure_fin)

    # Un scan de rattrapage se termine par un scoring : inutile de le doubler.
    if not _programmer_rattrapage(_planificateur):
        _planificateur.add_job(
            rescorer_tout,
            DateTrigger(run_date=datetime.now(_planificateur.timezone)
                        + timedelta(seconds=DELAI_RESCORING_SECONDES)),
            id=TACHE_RESCORING, replace_existing=True,
        )
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


def etat(utilisateur_id: int | None = None) -> dict:
    """Ce que l'interface affiche : actif, prochaine exécution, dernier scan.

    Le dernier scan est celui qui concerne le compte — le planifié ou l'un des
    siens : le scan manuel d'un autre ne lui apprend rien, et son nombre de
    nouveautés est celui de l'autre.
    """
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
        dernier = dernier_scan_abouti(session, utilisateur_id)
        nouvelles = dernier.nb_nouvelles if dernier else None
        if dernier is not None and utilisateur_id is not None:
            # Ce qui est entré dans SON fil : le scan planifié compte les
            # nouveautés de tous les comptes réunis.
            nouvelles = session.exec(
                select(func.count()).select_from(ScoreOffre)
                .where(ScoreOffre.utilisateur_id == utilisateur_id,
                       ScoreOffre.ajoutee_le >= dernier.started_at)).one()

        derniere_veille = session.exec(
            select(ScanRun).where(ScanRun.declenche_par == VEILLE)
            .order_by(ScanRun.started_at.desc()).limit(1)).first()

    veille = lire_reglages().veille
    return {
        "actif": r.scan_quotidien_actif and _planificateur is not None,
        "heure": f"{heure:02d}:{minute:02d}",
        "prochaine_execution": prochaine,
        "dernier_scan": dernier.started_at if dernier else None,
        "dernier_scan_nouvelles": nouvelles,
        "rattrapage_apres_heures": r.rattrapage_apres_heures,
        "veille": {
            "active": veille.active and _planificateur is not None,
            "intervalle_minutes": veille.intervalle_minutes,
            "heure_debut": veille.heure_debut,
            "heure_fin": veille.heure_fin,
            "sources": veille.sources,
            "derniere": derniere_veille.started_at if derniere_veille else None,
        },
    }
