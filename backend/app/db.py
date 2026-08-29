"""Connexion SQLite.

Tout est local : un seul fichier, aucun serveur à installer.
WAL activé pour que l'API et le planificateur puissent lire/écrire sans se bloquer.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from .config import reglages

# L'import peuple SQLModel.metadata : indispensable pour create_all et Alembic.
from . import models  # noqa: F401


def _chemin_db() -> Path:
    chemin = reglages().chemins.db
    chemin.parent.mkdir(parents=True, exist_ok=True)
    return chemin


def url_base() -> str:
    return f"sqlite:///{_chemin_db().as_posix()}"


# Le planificateur écrit depuis son propre thread pendant que l'API sert des
# requêtes : en WAL, SQLite n'autorise qu'un écrivain à la fois. Sans attente
# explicite, la seconde écriture échoue aussitôt en « database is locked » et
# l'utilisateur reçoit une erreur 500 pour un simple conflit passager.
ATTENTE_VERROU_SECONDES = 30

engine = create_engine(
    url_base(),
    echo=False,
    connect_args={
        # FastAPI sert les requêtes sur plusieurs threads : SQLite l'exige.
        "check_same_thread": False,
        "timeout": ATTENTE_VERROU_SECONDES,
    },
)


@event.listens_for(Engine, "connect")
def _pragmas_sqlite(dbapi_connection, connection_record) -> None:
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")     # sinon SQLite ignore les clés étrangères
    # FULL et non NORMAL : en WAL + NORMAL, une transaction validée peut encore
    # se perdre si la machine s'arrête brutalement. Le volume d'écriture de
    # l'application est minuscule — la sécurité ne coûte rien ici.
    cur.execute("PRAGMA synchronous=FULL")
    # Ceinture et bretelles : le `timeout` de la couche Python ne couvre pas
    # tous les chemins, ce pragma vaut pour la connexion elle-même.
    cur.execute(f"PRAGMA busy_timeout={ATTENTE_VERROU_SECONDES * 1000}")
    cur.close()


def checkpoint() -> None:
    """Rapatrie le journal WAL dans le fichier .db et le vide.

    Sans cela, les données récentes ne vivent que dans `dreamjob.db-wal` — un
    fichier annexe qu'une sauvegarde, un antivirus ou une copie manuelle peut
    laisser de côté. Appelé à l'arrêt de l'API.
    """
    with engine.connect() as connexion:
        connexion.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")


def creer_tables() -> None:
    """Filet de sécurité au démarrage. La référence reste Alembic."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """Dépendance FastAPI : une session par requête."""
    with Session(engine) as session:
        yield session
