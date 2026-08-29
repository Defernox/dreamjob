"""Fixtures communes : chaque test travaille sur une base SQLite jetable."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  (peuple SQLModel.metadata)

FIXTURES = Path(__file__).parent / "fixtures"

# Identifiants que la suite ne doit JAMAIS utiliser : un test qui passe parce
# qu'une clé traîne dans .env est un test qui mentira sur une autre machine —
# et qui consomme du quota au passage.
SECRETS_EXTERNES = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID",
    "FRANCE_TRAVAIL_CLIENT_ID", "FRANCE_TRAVAIL_CLIENT_SECRET",
    "ADZUNA_APP_ID", "ADZUNA_APP_KEY",
)


@pytest.fixture(autouse=True)
def sans_identifiants_reels(monkeypatch):
    """Coupe la suite de tests du monde extérieur.

    Les tests qui ont besoin d'un fournisseur le simulent explicitement ; aucun
    ne doit dépendre de ce qui se trouve dans le `.env` de la machine.
    """
    for nom in SECRETS_EXTERNES:
        monkeypatch.delenv(nom, raising=False)


@pytest.fixture
def engine(tmp_path):
    moteur = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    SQLModel.metadata.create_all(moteur)
    return moteur


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def client(engine):
    """API de test branchée sur la base jetable."""
    from app.db import get_session
    from app.main import app

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
