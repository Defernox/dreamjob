"""Les boutons d'avis des alertes Telegram : seule la conversation du propriétaire
compte, seul son fil est modifié, et un avis se corrige d'un second appui."""

from datetime import timedelta

import httpx
import pytest
from sqlmodel import select

from app.models import ScoreOffre, Utilisateur
from app.models.base import maintenant
from app.services import avis, notification

from .conftest import ajouter_offre

CONVERSATION = "4242"


@pytest.fixture(autouse=True)
def telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:jeton-de-test")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CONVERSATION)
    monkeypatch.setenv("DREAMJOB_URL", "https://dreamjob.exemple.ts.net")
    avis._reinitialiser()
    yield
    avis._reinitialiser()


@pytest.fixture
def api(monkeypatch):
    """L'API du bot simulée : `api.updates` est ce que rendra le prochain
    getUpdates, `api.appels` ce qui a été demandé."""
    class Api:
        updates: list = []
        appels: list = []

    def faux_post(url, json=None, timeout=None, **kw):
        methode = url.rsplit("/", 1)[1]
        Api.appels.append((methode, json))
        corps = {"ok": True, "result": Api.updates if methode == "getUpdates" else True}
        if methode == "getUpdates":
            Api.updates = []
        return httpx.Response(200, json=corps, request=httpx.Request("POST", url))

    Api.updates, Api.appels = [], []
    monkeypatch.setattr(avis.httpx, "post", faux_post)
    monkeypatch.setattr(notification.httpx, "post", faux_post)
    return Api


def _offre(session, n=1, score=95, utilisateur_id=None):
    o = ajouter_offre(session, utilisateur_id, source="t", source_id=str(n), hash=f"h{n}",
                      titre=f"Analyste {n}", entreprise="Banque", score=score,
                      ajoutee_le=maintenant() - timedelta(minutes=5))
    session.commit()
    return o


def _appui(update_id, offre_id, valeur, chat=CONVERSATION, message_id=77):
    return {"update_id": update_id, "callback_query": {
        "id": f"cq{update_id}", "data": f"avis:{offre_id}:{valeur}",
        "message": {"message_id": message_id, "chat": {"id": int(chat)}, "reply_markup": {
            "inline_keyboard": [
                [{"text": "Ouvrir dans DreamJob", "url": f"https://dreamjob.exemple.ts.net/offres/{offre_id}"}],
                notification.boutons_avis(offre_id)]}}}}


def _avis(session, offre_id):
    session.expire_all()
    return session.exec(select(ScoreOffre.avis).where(ScoreOffre.offer_id == offre_id)).first()


def test_chaque_alerte_porte_les_deux_boutons(session, api):
    from app.services.acces import proprietaire

    proprietaire(session)
    offre = _offre(session)
    assert notification.alerter(session, maintenant() - timedelta(hours=1)) == 1
    _, charge = api.appels[0]
    lignes = charge["reply_markup"]["inline_keyboard"]
    assert lignes[0][0]["url"].endswith(f"/offres/{offre.id}")
    assert [b["callback_data"] for b in lignes[1]] == [f"avis:{offre.id}:1", f"avis:{offre.id}:0"]


def test_le_resume_du_matin_n_a_pas_de_boutons_d_avis(session, api):
    """Un résumé couvre plusieurs offres : un appui ne saurait pas laquelle juger."""
    from app.services.acces import proprietaire

    proprietaire(session)
    _offre(session)
    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 1
    lignes = api.appels[0][1]["reply_markup"]["inline_keyboard"]
    assert all("callback_data" not in b for ligne in lignes for b in ligne)


def test_un_appui_du_proprietaire_est_enregistre_et_coche(engine, session, api):
    offre = _offre(session)
    api.updates = [_appui(10, offre.id, 1)]

    assert avis.relever(engine, attente=0) == 1
    assert _avis(session, offre.id) == 1
    methodes = [m for m, _ in api.appels]
    assert methodes == ["getUpdates", "answerCallbackQuery", "editMessageReplyMarkup"]
    clavier = api.appels[2][1]["reply_markup"]["inline_keyboard"]
    assert clavier[0][0]["text"] == "Ouvrir dans DreamJob", "le lien vers la fiche reste"
    assert clavier[1][0]["text"].startswith("✓ ") and not clavier[1][1]["text"].startswith("✓ ")


def test_un_second_appui_corrige_l_avis(engine, session, api):
    offre = _offre(session)
    api.updates = [_appui(10, offre.id, 1)]
    avis.relever(engine, attente=0)
    api.updates = [_appui(11, offre.id, 0)]
    avis.relever(engine, attente=0)
    assert _avis(session, offre.id) == 0
    # La seconde relève a confirmé la première : Telegram ne la renverra plus.
    offsets = [c.get("offset") for m, c in api.appels if m == "getUpdates"]
    assert offsets == [None, 11]


def test_une_autre_conversation_est_ignoree(engine, session, api):
    """Le bot se trouve par son nom : n'importe qui peut presser ses boutons."""
    offre = _offre(session)
    api.updates = [_appui(10, offre.id, 0, chat="999")]
    assert avis.relever(engine, attente=0) == 0
    assert _avis(session, offre.id) is None
    assert [m for m, _ in api.appels] == ["getUpdates"]


def test_une_offre_hors_du_fil_du_proprietaire_n_est_pas_touchee(engine, session, api):
    from app.services.acces import proprietaire

    proprietaire(session)
    ami = Utilisateur(email="ami@exemple.fr", mot_de_passe="")
    session.add(ami)
    session.commit()
    offre = _offre(session, utilisateur_id=ami.id)
    api.updates = [_appui(10, offre.id, 1)]

    assert avis.relever(engine, attente=0) == 0
    assert _avis(session, offre.id) is None
    assert api.appels[1][1]["text"] == "Offre introuvable."


@pytest.mark.parametrize("donnees", ["avis:abc:1", "avis:5:7", "autre:5:1", "avis:5", ""])
def test_une_reponse_mal_formee_est_ignoree(donnees):
    assert avis.lire_avis(donnees) is None


def test_sans_telegram_rien_n_est_demande(engine, api, monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ID")
    assert avis.relever(engine, attente=0) == 0
    assert api.appels == []
    assert avis.demarrer(engine) is False


def test_une_panne_de_telegram_ne_leve_pas_et_n_expose_pas_le_jeton(engine, monkeypatch, caplog):
    def en_panne(url, **kw):
        raise httpx.ConnectError(f"injoignable : {url}")

    monkeypatch.setattr(avis.httpx, "post", en_panne)
    with caplog.at_level("WARNING", logger="dreamjob.avis"):
        assert avis.relever(engine, attente=0) is None
    assert "jeton-de-test" not in caplog.text
