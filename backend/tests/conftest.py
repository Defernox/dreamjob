"""Fixtures communes : chaque test travaille sur une base SQLite jetable."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  (peuple SQLModel.metadata)

FIXTURES = Path(__file__).parent / "fixtures"

# Ce qui, d'une offre, appartient à celui qui la regarde : la note et « vue ».
CHAMPS_DE_NOTE = ("score", "score_detail", "score_explication", "scored_at",
                  "poids_version", "version_signaux", "vue", "ajoutee_le", "alertee_le", "doublon_de")


def ajouter_offre(session, utilisateur_id: int | None = None, **champs):
    """Crée une offre et la range dans le fil d'un compte — le propriétaire par
    défaut, comme en local. Les champs de note (`score`, `vue`…) vont à ce
    compte, le reste à l'offre. Ne valide pas la transaction."""
    from app.models import Offer, ScoreOffre
    from app.services.acces import proprietaire

    if utilisateur_id is None:
        utilisateur_id = proprietaire(session).id
    note = {k: champs.pop(k) for k in CHAMPS_DE_NOTE if k in champs}
    offre = Offer(**champs)
    session.add(offre)
    session.flush()
    session.add(ScoreOffre(utilisateur_id=utilisateur_id, offer_id=offre.id, **note))
    return offre

# Identifiants que la suite ne doit JAMAIS utiliser : un test qui passe parce
# qu'une clé traîne dans .env est un test qui mentira sur une autre machine —
# et qui consomme du quota au passage.
SECRETS_EXTERNES = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID",
    "FRANCE_TRAVAIL_CLIENT_ID", "FRANCE_TRAVAIL_CLIENT_SECRET",
    "ADZUNA_APP_ID", "ADZUNA_APP_KEY",
)


@pytest.fixture(autouse=True)
def sans_reseau(monkeypatch):
    """Aucun test ne sort sur le réseau.

    Neutraliser les identifiants ne suffit pas : une source publique comme
    Civiweb n'en demande aucun et partirait interroger le vrai serveur. On coupe
    donc le transport HTTP réel. `httpx.MockTransport`, utilisé par les tests du
    client HTTP, passe par une autre classe et reste opérationnel.
    """
    import httpx

    def interdit(self, request, *a, **kw):
        raise AssertionError(
            f"appel réseau interdit pendant les tests : {request.method} {request.url}"
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", interdit)


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
def client(engine, monkeypatch):
    """API de test branchée sur la base jetable.

    Le démarrage de l'application est neutralisé : il agissait sur la VRAIE
    base. `creer_tables()` y a créé les tables de comptes avant toute migration
    — l'autogénération Alembic est alors sortie vide — et chaque test
    sauvegardait la base réelle et démarrait le planificateur, qui pouvait
    programmer un scan de rattrapage.
    """
    import app.main as principal
    from app.db import get_session
    from app.main import app

    for nom in ("creer_tables", "sauvegarder", "demarrer_planificateur",
                "arreter_planificateur", "checkpoint"):
        monkeypatch.setattr(principal, nom, lambda *a, **kw: None)

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
