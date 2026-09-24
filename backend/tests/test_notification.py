"""Le résumé du matin : seulement quand il y a du vert, jamais bloquant, et
chacun le sien."""

from datetime import timedelta

import httpx
import pytest

from app.models import Profile, Utilisateur
from app.models.base import maintenant
from app.services import notification

from .conftest import ajouter_offre


@pytest.fixture
def envois(monkeypatch):
    partis = []

    def faux_post(url, content, headers, timeout):
        partis.append({"url": url, "corps": content.decode("utf-8"), "entetes": headers})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(notification.httpx, "post", faux_post)
    return partis


def _offre(session, n, score, vue=False, age_jours=0, utilisateur_id=None):
    o = ajouter_offre(session, utilisateur_id, source="t", source_id=str(n), hash=f"h{n}",
                      titre=f"Analyste {n}", entreprise="Banque", score=score, vue=vue,
                      ajoutee_le=maintenant() - timedelta(days=age_jours))
    session.commit()
    return o


def test_sans_sujet_configure_rien_ne_part(session, envois, monkeypatch):
    monkeypatch.delenv("NTFY_SUJET", raising=False)
    _offre(session, 1, 90)
    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 0
    assert envois == []


def test_seules_les_nouvelles_offres_vertes_non_vues_sont_signalees(session, envois, monkeypatch):
    monkeypatch.setenv("NTFY_SUJET", "sujet-de-test")
    depuis = maintenant() - timedelta(hours=1)
    _offre(session, 1, 91)
    _offre(session, 2, 80)
    _offre(session, 3, 60)                      # pas verte
    _offre(session, 4, 95, vue=True)            # déjà ouverte
    _offre(session, 5, 99, age_jours=3)         # d'un scan précédent

    assert notification.notifier(session, depuis) == 1
    envoi = envois[0]
    assert envoi["url"].endswith("/sujet-de-test")
    assert envoi["entetes"]["Title"].decode("utf-8") == "2 nouvelles offres vertes"
    assert envoi["corps"].splitlines() == ["91 — Analyste 1 · Banque", "80 — Analyste 2 · Banque"]


def test_aucune_offre_verte_aucune_notification(session, envois, monkeypatch):
    """Une alerte quotidienne « rien de nouveau » apprend à ignorer les autres."""
    monkeypatch.setenv("NTFY_SUJET", "sujet-de-test")
    _offre(session, 1, 55)
    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 0
    assert envois == []


def test_une_panne_de_ntfy_ne_fait_pas_echouer_le_scan(session, monkeypatch):
    monkeypatch.setenv("NTFY_SUJET", "sujet-de-test")
    _offre(session, 1, 90)

    def en_panne(*a, **kw):
        raise httpx.ConnectError("injoignable")

    monkeypatch.setattr(notification.httpx, "post", en_panne)
    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 0


# --- Plusieurs comptes ----------------------------------------------------------


def test_chacun_recoit_ses_offres_sur_son_sujet(session, envois, monkeypatch):
    monkeypatch.setenv("NTFY_SUJET", "sujet-du-proprietaire")
    from app.services.acces import proprietaire

    proprietaire(session)                       # le premier compte
    ami = Utilisateur(email="ami@exemple.fr", mot_de_passe="")
    session.add(ami)
    session.commit()
    session.add(Profile(utilisateur_id=ami.id, ntfy_sujet="sujet-de-l-ami"))
    _offre(session, 1, 91)
    _offre(session, 2, 85, utilisateur_id=ami.id)

    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 2
    par_sujet = {e["url"].rsplit("/", 1)[1]: e["corps"] for e in envois}
    assert par_sujet == {"sujet-du-proprietaire": "91 — Analyste 1 · Banque",
                         "sujet-de-l-ami": "85 — Analyste 2 · Banque"}


def test_le_sujet_de_l_env_n_est_qu_au_proprietaire(session, envois, monkeypatch):
    """Sans sujet dans son profil, un ami ne reçoit rien — surtout pas sur le
    téléphone du propriétaire."""
    monkeypatch.setenv("NTFY_SUJET", "sujet-du-proprietaire")
    from app.services.acces import proprietaire

    proprietaire(session)
    ami = Utilisateur(email="ami@exemple.fr", mot_de_passe="")
    session.add(ami)
    session.commit()
    _offre(session, 1, 91, utilisateur_id=ami.id)

    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 0
    assert envois == []
