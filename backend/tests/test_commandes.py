"""Les commandes du bot Telegram : le profil se lit et se retouche champ par
champ, l'Excel se récupère, et seul le propriétaire est écouté."""

import io

import httpx
import pytest
from openpyxl import load_workbook
from sqlmodel import select

from app.models import Application, Profile
from app.services import avis, commandes

from .conftest import ajouter_offre

CONVERSATION = "4242"


@pytest.fixture(autouse=True)
def telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:jeton-de-test")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CONVERSATION)
    avis._reinitialiser()
    yield
    avis._reinitialiser()


@pytest.fixture
def api(monkeypatch):
    class Api:
        updates: list = []
        appels: list = []

        @classmethod
        def textes(cls):
            return [c["text"] for m, c, _ in cls.appels if m == "sendMessage"]

    def faux_post(url, json=None, timeout=None, data=None, files=None, **kw):
        methode = url.rsplit("/", 1)[1]
        Api.appels.append((methode, json if json is not None else data, files))
        corps = {"ok": True, "result": Api.updates if methode == "getUpdates" else True}
        if methode == "getUpdates":
            Api.updates = []
        return httpx.Response(200, json=corps, request=httpx.Request("POST", url))

    Api.updates, Api.appels = [], []
    monkeypatch.setattr(httpx, "post", faux_post)
    return Api


@pytest.fixture
def recalculs(monkeypatch):
    """Les recalculs de notes demandés, sans les lancer."""
    demandes = []
    monkeypatch.setattr(commandes, "_executer", lambda fonction, *a: demandes.append(a[1:]))
    return demandes


@pytest.fixture
def moi(session):
    from app.services.acces import proprietaire

    compte = proprietaire(session)
    session.add(Profile(
        utilisateur_id=compte.id, prenom="Maxime", nom="Nicolas", ville="Caen",
        titre_vise="Analyste risques", contrats_acceptes=["CDI"], pays_acceptes=["France"],
        skills=[{"nom": "Excel", "niveau": "avancé", "ancree": True}],
        # Un bloc ancien, que le schéma d'aujourd'hui refuserait.
        langues=[{"libelle": "Français"}]))
    session.commit()
    return compte


def _ecrire(engine, api, texte, chat=CONVERSATION, update_id=10):
    api.updates = [{"update_id": update_id, "message": {
        "message_id": 5, "chat": {"id": int(chat)}, "text": texte}}]
    return avis.relever(engine, attente=0)


def _profil(session) -> Profile:
    session.expire_all()
    return session.exec(select(Profile)).one()


def test_profil_seul_montre_le_profil(engine, session, api, moi, recalculs):
    _ecrire(engine, api, "/profil")
    texte, = api.textes()
    assert "Maxime Nicolas" in texte and "<b>titre</b> : Analyste risques" in texte
    assert "competences (1)</b> : Excel" in texte
    assert recalculs == [], "lire ne recalcule rien"


def test_un_champ_simple_se_modifie_et_les_notes_sont_recalculees(engine, session, api, moi, recalculs):
    _ecrire(engine, api, "/profil Disponibilité Immédiate, dès janvier")
    assert _profil(session).disponibilite == "Immédiate, dès janvier"
    assert recalculs == [(moi.id,)]
    assert api.textes()[-1].startswith("✅ Profil mis à jour")


def test_un_tiret_vide_le_champ(engine, session, api, moi, recalculs):
    _ecrire(engine, api, "/profil ville -")
    assert _profil(session).ville == ""


def test_les_annees_d_experience_sont_un_nombre(engine, session, api, moi, recalculs):
    _ecrire(engine, api, "/profil experience trois", update_id=10)
    assert _profil(session).annees_experience == 0 and recalculs == []
    assert api.textes()[-1].startswith("❌")
    _ecrire(engine, api, "/profil expérience 3", update_id=11)
    assert _profil(session).annees_experience == 3


def test_une_valeur_hors_bornes_est_refusee_par_la_validation_de_l_interface(
        engine, session, api, moi, recalculs):
    _ecrire(engine, api, "/profil experience 99")
    assert _profil(session).annees_experience == 0
    assert api.textes()[-1].startswith("❌ Valeur refusée")


def test_une_competence_s_ajoute_et_se_retire(engine, session, api, moi, recalculs):
    _ecrire(engine, api, "/profil compétences + Python", update_id=10)
    assert _profil(session).noms_skills() == ["Excel", "Python"]
    _ecrire(engine, api, "/profil competences - excel", update_id=11)
    profil = _profil(session)
    assert profil.skills == [{"nom": "Python", "niveau": "", "ancree": False}]
    assert len(recalculs) == 2


def test_un_pays_s_ecrit_comme_le_vocabulaire_et_un_inconnu_est_refuse(engine, session, api, moi, recalculs):
    _ecrire(engine, api, "/profil pays_acceptes + suisse", update_id=10)
    assert _profil(session).pays_acceptes == ["France", "Suisse"]
    _ecrire(engine, api, "/profil pays_acceptes + Atlantide", update_id=11)
    assert _profil(session).pays_acceptes == ["France", "Suisse"]
    assert "Pays inconnu" in api.textes()[-1]


def test_un_contrat_inconnu_ou_deja_present_est_refuse(engine, session, api, moi, recalculs):
    _ecrire(engine, api, "/profil contrats + cdi", update_id=10)
    assert "déjà dans la liste" in api.textes()[-1]
    _ecrire(engine, api, "/profil contrats + Bénévolat", update_id=11)
    assert "Contrat inconnu" in api.textes()[-1]
    _ecrire(engine, api, "/profil contrats + v.i.e", update_id=12)
    assert _profil(session).contrats_acceptes == ["CDI", "V.I.E"]


def test_un_champ_inconnu_liste_les_champs(engine, session, api, moi, recalculs):
    _ecrire(engine, api, "/profil experiences_pro Banque")
    assert "Champ inconnu" in api.textes()[-1] and "disponibilite" in api.textes()[-1]
    assert recalculs == []


def test_excel_depose_le_justificatif(engine, session, api, moi):
    offre = ajouter_offre(session, moi.id, source="t", source_id="1", hash="h1",
                          titre="Analyste risques", entreprise="Banque", score=91)
    session.flush()
    session.add(Application(utilisateur_id=moi.id, offer_id=offre.id))
    session.commit()

    _ecrire(engine, api, "/excel")
    (_, donnees, fichiers), = [a for a in api.appels if a[0] == "sendDocument"]
    nom, contenu = fichiers["document"]
    assert nom.startswith("candidatures-") and nom.endswith(".xlsx")
    assert "1 candidature " in donnees["caption"]
    cellules = [c for ligne in load_workbook(io.BytesIO(contenu)).active.values for c in ligne]
    assert "Analyste risques" in cellules and "Banque" in cellules


def test_excel_sans_candidature_le_dit(engine, session, api, moi):
    _ecrire(engine, api, "/excel")
    assert api.textes() == ["Aucune candidature dans votre suivi pour l'instant."]


def test_candidatures_liste_les_dernieres(engine, session, api, moi):
    offre = ajouter_offre(session, moi.id, source="t", source_id="1", hash="h1",
                          titre="Analyste risques", entreprise="Banque", score=91)
    session.flush()
    session.add(Application(utilisateur_id=moi.id, offer_id=offre.id))
    session.commit()
    _ecrire(engine, api, "/candidatures")
    assert "Envoyée · Analyste risques · Banque" in api.textes()[-1]


def test_un_message_quelconque_recoit_l_aide(engine, session, api, moi):
    _ecrire(engine, api, "bonjour")
    assert "/profil" in api.textes()[-1] and "/excel" in api.textes()[-1]


def test_un_inconnu_ne_lit_pas_le_profil(engine, session, api, moi, recalculs):
    """Le bot se trouve par son nom : n'importe qui peut lui écrire."""
    _ecrire(engine, api, "/profil", chat="999", update_id=10)
    _ecrire(engine, api, "/profil ville Paris", chat="999", update_id=11)
    assert api.textes() == [] and _profil(session).ville == "Caen"


def test_la_releve_demande_aussi_les_messages(engine, api):
    avis.relever(engine, attente=0)
    assert api.appels[0][1]["allowed_updates"] == ["callback_query", "message"]


def test_les_commandes_sont_annoncees_a_telegram(api):
    commandes.annoncer()
    (methode, charge, _), = api.appels
    assert methode == "setMyCommands"
    assert [c["command"] for c in charge["commands"]] == [
        "profil", "excel", "candidatures", "motscles", "aide"]


def test_motscles_liste_ce_que_les_offres_vertes_demandent_et_que_le_profil_ne_dit_pas(
        engine, session, api, moi):
    for n in range(3):
        ajouter_offre(session, moi.id, source="t", source_id=str(n), hash=f"h{n}", score=90,
                      titre="Gestionnaire middle office", entreprise="Banque",
                      description_brute="Le middle office suit les opérations du middle office.")
    session.commit()
    _ecrire(engine, api, "/motscles")
    texte = api.textes()[-1]
    assert "3 offres vertes" in texte and "• middle office — 3 offres" in texte
    assert "N'ajoutez que ce que vous avez réellement pratiqué" in texte


def test_motscles_sans_offre_verte_le_dit(engine, session, api, moi):
    _ecrire(engine, api, "/motscles")
    assert api.textes() == ["Aucune offre verte pour l'instant : rien à comparer."]
