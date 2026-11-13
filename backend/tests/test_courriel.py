"""La candidature par e-mail : une adresse ne se devine pas, le message est
fixe, et un refus du serveur se dit en français sans rien noter."""

import smtplib

import pytest

from app.models import Offer, Profile
from app.services import courriel


def _offre(**champs) -> Offer:
    base = dict(source="france_travail", source_id="198ABC", titre="Analyste risques (H/F)",
                entreprise="Banque", lieu="Paris", description_brute="Poste à pourvoir.", raw={})
    return Offer(**(base | champs))


@pytest.fixture
def profil() -> Profile:
    return Profile(prenom="Maxime", nom="Nicolas", email="maxime@exemple.fr",
                   telephone="06 00 00 00 00")


@pytest.fixture
def boite(monkeypatch) -> courriel.Boite:
    monkeypatch.setenv("SMTP_HOTE", "smtp.exemple.fr")
    monkeypatch.setenv("SMTP_UTILISATEUR", "envoi@exemple.fr")
    monkeypatch.setenv("SMTP_MOT_DE_PASSE", "abcd efgh ijkl mnop")
    return courriel.boite()


# --- L'adresse ---------------------------------------------------------------

def test_l_adresse_du_contact_france_travail_est_retenue():
    offre = _offre(raw={"contact": {"courriel": "recrutement@banque.fr"}})
    assert courriel.adresse_de_candidature(offre) == "recrutement@banque.fr"


def test_un_contact_qui_n_est_qu_une_phrase_ne_donne_pas_d_adresse():
    """France Travail range parfois un lien dans le champ « courriel »."""
    offre = _offre(raw={"contact": {
        "courriel": "Pour postuler, utiliser le lien suivant : https://banque.fr/offre/12",
        "urlPostulation": "https://banque.fr/offre/12"}})
    assert courriel.adresse_de_candidature(offre) == ""
    assert courriel.page_de_candidature(offre) == "https://banque.fr/offre/12"


def test_une_adresse_du_texte_n_est_retenue_qu_invitee():
    invitee = _offre(description_brute="Merci d'envoyer votre CV et votre lettre à rh@fonds.fr.")
    citee = _offre(description_brute="Notre siège : 3 rue de la Paix. Standard : accueil@fonds.fr")
    assert courriel.adresse_de_candidature(invitee) == "rh@fonds.fr"
    assert courriel.adresse_de_candidature(citee) == ""


def test_la_boite_des_donnees_personnelles_n_est_jamais_une_adresse_de_candidature():
    offre = _offre(description_brute=(
        "Pour toute question sur le traitement de votre candidature, écrivez à dpo@banque.fr."))
    assert courriel.adresse_de_candidature(offre) == ""


def test_sans_lien_de_candidature_la_page_est_l_annonce():
    assert courriel.page_de_candidature(_offre(url="https://exemple.fr/a")) == "https://exemple.fr/a"


# --- La boîte d'envoi --------------------------------------------------------

def test_une_boite_incomplete_n_est_pas_une_boite(monkeypatch):
    monkeypatch.setenv("SMTP_HOTE", "smtp.exemple.fr")
    assert courriel.boite() is None


def test_le_mot_de_passe_d_application_est_lu_sans_ses_espaces(boite):
    assert boite.mot_de_passe == "abcdefghijklmnop"
    assert (boite.port, boite.expediteur) == (587, "envoi@exemple.fr")


# --- Le message --------------------------------------------------------------

def test_le_message_porte_l_intitule_nettoye_la_reference_et_les_pieces(profil, boite, tmp_path):
    cv, lettre = tmp_path / "CV_Maxime_Nicolas.pdf", tmp_path / "Lettre_de_motivation_Maxime_Nicolas.pdf"
    cv.write_bytes(b"%PDF cv")
    lettre.write_bytes(b"%PDF lettre")
    message = courriel.composer(profil, _offre(), "rh@banque.fr", [cv, lettre], boite)

    assert message["To"] == "rh@banque.fr"
    assert message["Subject"] == "Candidature – Analyste risques (offre n° 198ABC) – Maxime Nicolas"
    assert "envoi@exemple.fr" in message["From"] and "Maxime Nicolas" in message["From"]
    # Le recruteur répond à l'adresse du CV, pas à la boîte d'envoi.
    assert message["Reply-To"] == "maxime@exemple.fr"
    assert [p.get_filename() for p in message.iter_attachments()] == [cv.name, lettre.name]
    corps = message.get_body(("plain",)).get_content()
    assert "Analyste risques" in corps and "06 00 00 00 00" in corps


def test_une_annonce_en_anglais_recoit_un_message_en_anglais(profil, boite):
    offre = _offre(source="workday", titre="Risk Analyst", description_brute=(
        "We are looking for a risk analyst to join the team. You will work with the "
        "trading desks and the risk managers, and you will be responsible for the daily "
        "reports that are sent to the management of the bank."))
    message = courriel.composer(profil, offre, "jobs@bank.com", [], boite)
    assert message["Subject"] == "Application – Risk Analyst – Maxime Nicolas"
    assert "Kind regards" in message.get_body(("plain",)).get_content()


# --- L'envoi -----------------------------------------------------------------

class FauxServeur:
    """Un serveur d'envoi qui retient ce qu'on lui remet."""
    envois: list = []
    refuse_la_connexion = False

    def __init__(self, hote, port, **kw):
        self.hote, self.port = hote, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, **kw):
        pass

    def login(self, utilisateur, mot_de_passe):
        if FauxServeur.refuse_la_connexion:
            raise smtplib.SMTPAuthenticationError(535, b"mot de passe refuse")

    def send_message(self, message, to_addrs=None):
        FauxServeur.envois.append((message, to_addrs))
        return {}


@pytest.fixture
def serveur(monkeypatch):
    FauxServeur.envois, FauxServeur.refuse_la_connexion = [], False
    monkeypatch.setattr(courriel.smtplib, "SMTP", FauxServeur)
    monkeypatch.setattr(courriel.smtplib, "SMTP_SSL", FauxServeur)
    return FauxServeur


def test_l_envoi_met_l_expediteur_en_copie_cachee(profil, boite, serveur):
    message = courriel.composer(profil, _offre(), "rh@banque.fr", [], boite)
    courriel.envoyer(message, boite)
    (_, destinataires), = serveur.envois
    assert destinataires == ["rh@banque.fr", "envoi@exemple.fr"]
    assert "Bcc" not in message, "la copie ne doit pas se lire dans le message"


def test_un_mot_de_passe_refuse_se_dit_en_francais_sans_le_montrer(profil, boite, serveur):
    serveur.refuse_la_connexion = True
    message = courriel.composer(profil, _offre(), "rh@banque.fr", [], boite)
    with pytest.raises(courriel.CourrielErreur) as erreur:
        courriel.envoyer(message, boite)
    assert "mot de passe d'application" in str(erreur.value)
    assert "abcdefghijklmnop" not in str(erreur.value)
    assert serveur.envois == []
