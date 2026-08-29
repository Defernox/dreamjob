"""Le scan quotidien.

Le point délicat : DreamJob n'est pas un serveur. Si l'application est fermée à
l'heure du rendez-vous, personne ne le rattrape — d'où le déclencheur de
démarrage, dont dépend l'utilité réelle de la fonction.
"""

from datetime import timedelta

import pytest
from sqlmodel import Session

from app.config import Planification
from app.models import ScanRun
from app.models.base import maintenant
from app.models.enums import StatutScan
from app.scheduler import dernier_scan_abouti


# --- Lecture de l'heure -----------------------------------------------------


@pytest.mark.parametrize("saisie, attendu", [
    ("07:30", (7, 30)), ("6:05", (6, 5)), ("23:59", (23, 59)), ("00:00", (0, 0)),
])
def test_heures_valides(saisie, attendu):
    assert Planification(heure=saisie).heure_minute() == attendu


@pytest.mark.parametrize("saisie", ["midi", "25:00", "07:99", "", "7h30"])
def test_une_heure_illisible_ne_bloque_pas_le_demarrage(saisie):
    """Une faute de frappe dans config.yaml ne doit pas empêcher l'app de démarrer."""
    assert Planification(heure=saisie).heure_minute() == (7, 30)


# --- Choix du dernier scan de référence -------------------------------------


def _scan(session, *, il_y_a_heures: float, statut: str, nouvelles: int = 0) -> ScanRun:
    scan = ScanRun(
        started_at=maintenant() - timedelta(hours=il_y_a_heures),
        statut=statut, nb_nouvelles=nouvelles,
    )
    session.add(scan)
    session.commit()
    return scan


def test_sans_historique_il_n_y_a_pas_de_dernier_scan(session):
    assert dernier_scan_abouti(session) is None


def test_le_dernier_scan_abouti_est_retenu(session):
    _scan(session, il_y_a_heures=30, statut=StatutScan.TERMINE.value)
    recent = _scan(session, il_y_a_heures=2, statut=StatutScan.TERMINE.value, nouvelles=5)
    assert dernier_scan_abouti(session).id == recent.id


def test_un_scan_en_echec_ne_compte_pas(session):
    """Sinon une panne de source ferait croire que la veille est à jour, et le
    rattrapage ne se déclencherait jamais."""
    reussi = _scan(session, il_y_a_heures=40, statut=StatutScan.TERMINE.value)
    _scan(session, il_y_a_heures=1, statut=StatutScan.ECHEC.value)
    assert dernier_scan_abouti(session).id == reussi.id


def test_un_scan_partiel_compte_comme_abouti(session):
    """Une source sur trois en panne : les offres des deux autres sont bien là."""
    partiel = _scan(session, il_y_a_heures=1, statut=StatutScan.PARTIEL.value, nouvelles=3)
    _scan(session, il_y_a_heures=40, statut=StatutScan.TERMINE.value)
    assert dernier_scan_abouti(session).id == partiel.id


def test_un_scan_en_cours_ne_compte_pas_encore(session):
    termine = _scan(session, il_y_a_heures=10, statut=StatutScan.TERMINE.value)
    _scan(session, il_y_a_heures=0, statut=StatutScan.EN_COURS.value)
    assert dernier_scan_abouti(session).id == termine.id


# --- Le scan planifié n'invente rien ---------------------------------------


def test_le_scan_planifie_est_trace_comme_tel(session, monkeypatch):
    """Pour distinguer, dans l'historique, ce que l'utilisateur a lancé de ce que
    l'application a fait toute seule."""
    from app import scheduler
    from app.connectors import registry
    from app.connectors.base import BaseConnector
    from app.services import scan as service_scan

    class SourceMuette(BaseConnector):
        cle = libelle = "muette"

        def fetch(self, query):
            return []

    monkeypatch.setattr(registry, "CONNECTEURS", {"muette": SourceMuette})
    # `cles_actives` est importé par son nom dans scan.py : c'est là qu'il faut
    # le remplacer, pas dans son module d'origine.
    monkeypatch.setattr(service_scan, "cles_actives", lambda r: ["muette"])
    monkeypatch.setattr(scheduler, "engine", session.get_bind())

    scheduler.executer_scan("planifie")

    # Le scan a écrit depuis une autre session : la nôtre doit relire.
    session.expire_all()
    scan = dernier_scan_abouti(session)
    assert scan is not None
    assert scan.declenche_par == "planifie"
    assert scan.nb_appels_llm == 0


def test_une_source_qui_explose_ne_tue_pas_le_planificateur(session, monkeypatch):
    """Une exception qui remonterait laisserait le planificateur muet jusqu'au
    prochain redémarrage."""
    from app import scheduler

    def boum(*a, **kw):
        raise RuntimeError("panne totale")

    monkeypatch.setattr(scheduler, "lancer_scan", boum)
    monkeypatch.setattr(scheduler, "engine", session.get_bind())
    scheduler.executer_scan("planifie")      # ne doit pas lever
