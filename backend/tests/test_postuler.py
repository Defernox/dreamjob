"""Postuler depuis Telegram : oui prépare et propose, rien ne part sans un second
appui, et une candidature ne se note qu'une fois."""

import json
from datetime import timedelta

import httpx
import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.config import reglages
from app.models import Application, Profile, ScoreOffre, Utilisateur
from app.models.base import maintenant
from app.schemas.document import ResultatDocuments
from app.services import avis, courriel, postuler

from .conftest import ajouter_offre

CONVERSATION = "4242"


@pytest.fixture(autouse=True)
def telegram(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:jeton-de-test")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CONVERSATION)
    monkeypatch.setattr(reglages().chemins, "dossier_candidatures", str(tmp_path / "candidatures"))
    # La génération tourne d'ordinaire dans son fil : ici, sur place.
    monkeypatch.setattr(postuler, "_executer", lambda fonction, *a: fonction(*a))
    avis._reinitialiser()
    postuler._occupees.clear()
    yield
    avis._reinitialiser()
    postuler._occupees.clear()


@pytest.fixture
def api(monkeypatch):
    """L'API du bot simulée : `api.appels` retient (méthode, charge, fichiers)."""
    class Api:
        updates: list = []
        appels: list = []

        @classmethod
        def de(cls, methode):
            return [c for m, c, _ in cls.appels if m == methode]

        @classmethod
        def fichiers(cls):
            return [f["document"][0] for m, _, f in cls.appels if m == "sendDocument"]

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
def moi(session):
    from app.services.acces import proprietaire

    compte = proprietaire(session)
    session.add(Profile(utilisateur_id=compte.id, prenom="Maxime", nom="Nicolas",
                        email="maxime@exemple.fr", telephone="06 00 00 00 00"))
    session.commit()
    return compte


@pytest.fixture
def generation(monkeypatch):
    """Remplace la vraie génération : écrit un dossier avec ses deux PDF, comme
    elle, et compte ses appels. `generation.refus` la fait échouer."""
    import app.api.documents as documents

    class Generation:
        appels: list = []
        refus: str | None = None
        avertissements: list = []

    def fausse(offre_id, ouvrir_dossier=None, session=None, moi=None):
        Generation.appels.append(offre_id)
        if Generation.refus:
            raise HTTPException(502, Generation.refus)
        from app.models import Offer
        offre = session.get(Offer, offre_id)
        dossier = reglages().chemins.candidatures / f"2026-11-13_offre-{offre_id}"
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / "CV_Maxime_Nicolas.pdf").write_bytes(b"%PDF cv")
        (dossier / "Lettre_de_motivation_Maxime_Nicolas.pdf").write_bytes(b"%PDF lettre")
        (dossier / "offre.json").write_text(json.dumps(
            {"source": offre.source, "source_id": offre.source_id}), encoding="utf-8")
        (dossier / "generation.json").write_text(json.dumps({"cout_usd": 0.0812}), encoding="utf-8")
        return ResultatDocuments(dossier=str(dossier), fichiers=[], lettre_essais=1, ouvert=False,
                                 avertissements=list(Generation.avertissements))

    Generation.appels, Generation.refus, Generation.avertissements = [], None, []
    monkeypatch.setattr(documents, "generer_documents", fausse)
    return Generation


@pytest.fixture
def boite(monkeypatch):
    """Une boîte d'envoi réglée, et un serveur qui retient ce qu'on lui remet."""
    class Serveur:
        envois: list = []
        en_panne = False

        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, **kw): pass
        def login(self, *a): pass

        def send_message(self, message, to_addrs=None):
            if Serveur.en_panne:
                raise OSError("connexion coupée")
            Serveur.envois.append((message, to_addrs))
            return {}

    Serveur.envois, Serveur.en_panne = [], False
    monkeypatch.setenv("SMTP_HOTE", "smtp.exemple.fr")
    monkeypatch.setenv("SMTP_UTILISATEUR", "envoi@exemple.fr")
    monkeypatch.setenv("SMTP_MOT_DE_PASSE", "secret")
    monkeypatch.setattr(courriel.smtplib, "SMTP", Serveur)
    return Serveur


def _offre(session, n=1, utilisateur_id=None, **champs):
    base = dict(source="t", source_id=str(n), hash=f"h{n}", titre=f"Analyste {n}",
                entreprise="Banque", url=f"https://banque.exemple/offre/{n}", score=95,
                ajoutee_le=maintenant() - timedelta(minutes=5))
    o = ajouter_offre(session, utilisateur_id, **(base | champs))
    session.commit()
    return o


def _appui(update_id, offre_id, action, chat=CONVERSATION):
    return {"update_id": update_id, "callback_query": {
        "id": f"cq{update_id}", "data": f"post:{offre_id}:{action}",
        "message": {"message_id": 77, "chat": {"id": int(chat)}, "reply_markup": {
            "inline_keyboard": [
                [{"text": "Ouvrir dans DreamJob", "url": f"https://dreamjob.exemple/offres/{offre_id}"}],
                postuler.boutons_postuler(offre_id)]}}}}


def _appuyer(engine, api, offre_id, action, update_id=10, **kw):
    api.updates = [_appui(update_id, offre_id, action, **kw)]
    return avis.relever(engine, attente=0)


def _avis(session, offre_id):
    session.expire_all()
    return session.exec(select(ScoreOffre.avis).where(ScoreOffre.offer_id == offre_id)).first()


def _candidatures(session):
    session.expire_all()
    return session.exec(select(Application)).all()


def _donnees(clavier):
    return [b.get("callback_data") or b.get("url") for ligne in clavier for b in ligne]


# --- Oui / Non ---------------------------------------------------------------

def test_oui_prepare_le_dossier_le_depose_et_demande_la_validation(engine, session, api, moi, generation):
    offre = _offre(session)
    assert _appuyer(engine, api, offre.id, "oui") == 1

    assert _avis(session, offre.id) == 1, "postuler vaut avis favorable, pour mesurer le score"
    assert generation.appels == [offre.id]
    assert api.fichiers() == ["CV_Maxime_Nicolas.pdf", "Lettre_de_motivation_Maxime_Nicolas.pdf"]
    proposition = api.de("sendMessage")[-1]
    assert "Dossier prêt" in proposition["text"] and "0,08 $" in proposition["text"]
    # Sans adresse de candidature : le lien, la copie, « C'est envoyé ».
    assert _donnees(proposition["reply_markup"]["inline_keyboard"]) == [
        offre.url, f"post:{offre.id}:txt", f"post:{offre.id}:fait",
        f"post:{offre.id}:ref", f"post:{offre.id}:ann"]
    assert _candidatures(session) == [], "rien n'est noté avant la validation"


def test_l_alerte_garde_son_lien_et_coche_la_reponse(engine, session, api, moi, generation):
    offre = _offre(session)
    _appuyer(engine, api, offre.id, "oui")
    clavier = api.de("editMessageReplyMarkup")[0]["reply_markup"]["inline_keyboard"]
    assert clavier[0][0]["text"] == "Ouvrir dans DreamJob"
    assert clavier[1][0]["text"].startswith("✓ ") and not clavier[1][1]["text"].startswith("✓ ")


def test_non_note_l_avis_et_ne_genere_rien(engine, session, api, moi, generation):
    offre = _offre(session)
    assert _appuyer(engine, api, offre.id, "non") == 1
    assert _avis(session, offre.id) == 0
    assert generation.appels == [] and api.fichiers() == []


def test_les_avertissements_du_dossier_sont_montres(engine, session, api, moi, generation):
    generation.avertissements = ["Lettre livrée, mais elle contient des formules convenues : <dynamique>"]
    offre = _offre(session)
    _appuyer(engine, api, offre.id, "oui")
    texte = api.de("sendMessage")[-1]["text"]
    assert "⚠️ Lettre livrée" in texte
    assert "&lt;dynamique&gt;" in texte, "un texte venu du dossier n'est pas une balise"


def test_une_generation_refusee_se_dit_avec_de_quoi_reessayer(engine, session, api, moi, generation):
    generation.refus = "Votre crédit Anthropic est épuisé."
    offre = _offre(session)
    _appuyer(engine, api, offre.id, "oui")
    message = api.de("sendMessage")[-1]
    assert "crédit Anthropic est épuisé" in message["text"]
    assert _donnees(message["reply_markup"]["inline_keyboard"]) == [
        f"post:{offre.id}:ref", f"post:{offre.id}:ann"]
    assert postuler._occupees == set(), "l'offre est libérée : on peut réessayer"


def test_deux_appuis_impatients_ne_paient_qu_un_dossier(engine, session, api, moi, generation, monkeypatch):
    lancees = []
    monkeypatch.setattr(postuler, "_executer", lambda fonction, *a: lancees.append(a))
    offre = _offre(session)
    _appuyer(engine, api, offre.id, "oui", update_id=10)
    _appuyer(engine, api, offre.id, "oui", update_id=11)
    assert len(lancees) == 1
    assert api.de("answerCallbackQuery")[-1]["text"] == "Les documents sont déjà en préparation."


def test_refaire_regenere_sans_toucher_a_l_avis(engine, session, api, moi, generation):
    offre = _offre(session)
    assert _appuyer(engine, api, offre.id, "ref") == 0
    assert generation.appels == [offre.id] and _avis(session, offre.id) is None
    assert api.de("editMessageReplyMarkup")[0]["reply_markup"] == {"inline_keyboard": []}


# --- Envoi par e-mail --------------------------------------------------------

def test_une_adresse_de_candidature_propose_l_envoi(engine, session, api, moi, generation, boite):
    offre = _offre(session, raw={"contact": {"courriel": "rh@banque.fr"}})
    _appuyer(engine, api, offre.id, "oui")
    proposition = api.de("sendMessage")[-1]
    assert "rh@banque.fr" in proposition["text"]
    assert _donnees(proposition["reply_markup"]["inline_keyboard"]) == [
        f"post:{offre.id}:env", f"post:{offre.id}:ref", f"post:{offre.id}:ann"]
    assert boite.envois == [], "proposer n'est pas envoyer"


def test_sans_boite_d_envoi_l_adresse_est_montree_mais_rien_n_est_automatique(
        engine, session, api, moi, generation):
    offre = _offre(session, raw={"contact": {"courriel": "rh@banque.fr"}})
    _appuyer(engine, api, offre.id, "oui")
    proposition = api.de("sendMessage")[-1]
    assert "rh@banque.fr" in proposition["text"] and "n'est pas réglé" in proposition["text"]
    assert f"post:{offre.id}:env" not in _donnees(proposition["reply_markup"]["inline_keyboard"])


def test_envoyer_fait_partir_l_e_mail_et_note_la_candidature(engine, session, api, moi, generation, boite):
    offre = _offre(session, raw={"contact": {"courriel": "rh@banque.fr"}})
    _appuyer(engine, api, offre.id, "oui", update_id=10)
    _appuyer(engine, api, offre.id, "env", update_id=11)

    (message, destinataires), = boite.envois
    assert destinataires == ["rh@banque.fr", "envoi@exemple.fr"]
    assert [p.get_filename() for p in message.iter_attachments()] == [
        "CV_Maxime_Nicolas.pdf", "Lettre_de_motivation_Maxime_Nicolas.pdf"]
    candidature, = _candidatures(session)
    assert (candidature.offer_id, candidature.contact, candidature.statut) == (
        offre.id, "rh@banque.fr", "Envoyée")
    assert "par e-mail" in candidature.notes and candidature.dossier_local
    assert "Candidature envoyée à rh@banque.fr" in api.de("sendMessage")[-1]["text"]


def test_un_second_appui_sur_envoyer_n_envoie_pas_deux_fois(engine, session, api, moi, generation, boite):
    offre = _offre(session, raw={"contact": {"courriel": "rh@banque.fr"}})
    _appuyer(engine, api, offre.id, "oui", update_id=10)
    _appuyer(engine, api, offre.id, "env", update_id=11)
    _appuyer(engine, api, offre.id, "env", update_id=12)
    assert len(boite.envois) == 1 and len(_candidatures(session)) == 1


def test_un_e_mail_qui_ne_part_pas_n_est_pas_note(engine, session, api, moi, generation, boite):
    boite.en_panne = True
    offre = _offre(session, raw={"contact": {"courriel": "rh@banque.fr"}})
    _appuyer(engine, api, offre.id, "oui", update_id=10)
    _appuyer(engine, api, offre.id, "env", update_id=11)
    assert _candidatures(session) == []
    assert "n'est pas parti" in api.de("sendMessage")[-1]["text"]
    assert postuler._occupees == set(), "l'envoi peut être retenté"


def test_envoyer_sans_dossier_ne_fait_rien_partir(engine, session, api, moi, boite):
    offre = _offre(session, raw={"contact": {"courriel": "rh@banque.fr"}})
    _appuyer(engine, api, offre.id, "env")
    assert boite.envois == [] and _candidatures(session) == []


# --- Mode assisté ------------------------------------------------------------

def test_c_est_envoye_note_la_candidature_une_seule_fois(engine, session, api, moi, generation):
    offre = _offre(session)
    _appuyer(engine, api, offre.id, "oui", update_id=10)
    _appuyer(engine, api, offre.id, "fait", update_id=11)
    _appuyer(engine, api, offre.id, "fait", update_id=12)
    candidature, = _candidatures(session)
    assert candidature.offer_id == offre.id and "Déposée sur le site" in candidature.notes
    assert candidature.dossier_local.endswith(f"offre-{offre.id}")


def test_le_lien_de_candidature_de_l_annonce_prime_sur_l_annonce(engine, session, api, moi, generation):
    offre = _offre(session, raw={"contact": {"urlPostulation": "https://banque.exemple/postuler/9"}})
    _appuyer(engine, api, offre.id, "oui")
    clavier = api.de("sendMessage")[-1]["reply_markup"]["inline_keyboard"]
    assert clavier[0][0]["url"] == "https://banque.exemple/postuler/9"


def test_a_copier_donne_les_coordonnees_une_par_ligne(engine, session, api, moi, generation):
    offre = _offre(session)
    _appuyer(engine, api, offre.id, "txt")
    message = api.de("sendMessage")[-1]
    assert message["parse_mode"] == "HTML"
    assert "<code>maxime@exemple.fr</code>" in message["text"]
    assert "<code>06 00 00 00 00</code>" in message["text"]


def test_annuler_ne_note_rien(engine, session, api, moi, generation):
    offre = _offre(session)
    _appuyer(engine, api, offre.id, "oui", update_id=10)
    _appuyer(engine, api, offre.id, "ann", update_id=11)
    assert _candidatures(session) == []
    assert "Rien n'a été envoyé" in api.de("sendMessage")[-1]["text"]


# --- Garde-fous --------------------------------------------------------------

def test_une_autre_conversation_ne_declenche_rien(engine, session, api, moi, generation):
    offre = _offre(session)
    assert _appuyer(engine, api, offre.id, "oui", chat="999") == 0
    assert generation.appels == [] and _avis(session, offre.id) is None


def test_une_offre_hors_du_fil_du_proprietaire_n_est_pas_touchee(engine, session, api, moi, generation):
    ami = Utilisateur(email="ami@exemple.fr", mot_de_passe="")
    session.add(ami)
    session.commit()
    offre = _offre(session, utilisateur_id=ami.id)
    assert _appuyer(engine, api, offre.id, "oui") == 0
    assert generation.appels == [] and _candidatures(session) == []
    assert api.de("answerCallbackQuery")[0]["text"] == "Offre introuvable."


def test_on_ne_repostule_pas_a_une_offre_deja_postulee(engine, session, api, moi, generation):
    offre = _offre(session)
    session.add(Application(utilisateur_id=moi.id, offer_id=offre.id))
    session.commit()
    _appuyer(engine, api, offre.id, "oui")
    assert generation.appels == []
    assert api.de("answerCallbackQuery")[0]["text"] == "Vous avez déjà postulé à cette offre."


@pytest.mark.parametrize("donnees", ["post:abc:oui", "post:5:peut-etre", "avis:5:1", "post:5", ""])
def test_un_bouton_mal_forme_est_ignore(donnees):
    assert postuler.lire(donnees) is None


# --- Ce que le logiciel de recrutement fera du dossier ------------------------

def test_le_dossier_dit_ce_que_le_logiciel_de_l_employeur_fera_du_cv(engine, session, api, moi, generation):
    offre = _offre(session, raw={"employeur": "Banque", "logiciel": "greenhouse"})
    _appuyer(engine, api, offre.id, "oui")
    texte = api.de("sendMessage")[-1]["text"]
    assert "<b>Greenhouse</b>" in texte and "questions du formulaire" in texte


def test_un_site_inconnu_ne_recoit_aucun_conseil_invente(engine, session, api, moi, generation):
    offre = _offre(session)
    _appuyer(engine, api, offre.id, "oui")
    assert "🏢" not in api.de("sendMessage")[-1]["text"]


def test_le_word_est_joint_quand_le_logiciel_le_lit_mieux(engine, session, api, moi, generation, monkeypatch):
    import app.api.documents as documents

    vraie = documents.generer_documents

    def avec_word(offre_id, **kw):
        resultat = vraie(offre_id, **kw)
        (reglages().chemins.candidatures / f"2026-11-13_offre-{offre_id}" / "CV_Maxime_Nicolas.docx"
         ).write_bytes(b"PK word")
        return resultat

    monkeypatch.setattr(documents, "generer_documents", avec_word)
    offre = _offre(session, raw={"employeur": "Banque", "logiciel": "oracle"})
    _appuyer(engine, api, offre.id, "oui")
    assert api.fichiers() == ["CV_Maxime_Nicolas.pdf", "Lettre_de_motivation_Maxime_Nicolas.pdf",
                              "CV_Maxime_Nicolas.docx"]


def test_une_exigence_hors_de_portee_est_annoncee_avant_le_formulaire(engine, session, api, moi, generation):
    """Les questions de présélection sont le vrai rejet automatique."""
    profil = session.exec(select(Profile)).one()
    profil.annees_experience = 2
    session.add(profil)
    offre = _offre(session, description_brute="Vous justifiez de 5 ans d'expérience minimum en banque.")
    _appuyer(engine, api, offre.id, "oui")
    texte = api.de("sendMessage")[-1]["text"]
    assert "Questions éliminatoires possibles" in texte and "5 ans" in texte and "profil : 2" in texte
