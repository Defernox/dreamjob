"""Ce que l'alerte dit de l'offre : le salaire annoncé — jamais estimé, jamais
confondu avec un autre montant — et les missions telles que l'annonce les écrit."""

from datetime import timedelta

import httpx
import pytest

from app.models import Offer
from app.models.base import maintenant
from app.services import apercu, notification

from .conftest import ajouter_offre


def _offre(description="", **champs) -> Offer:
    base = dict(source="t", source_id="1", titre="Analyste risques", description_brute=description, raw={})
    return Offer(**(base | champs))


# --- Le salaire que la source donne ------------------------------------------

@pytest.mark.parametrize("salaire, attendu", [
    ({"libelle": "Annuel de 45000.0 Euros à 52000.0 Euros sur 12.0 mois"},
     "Annuel de 45 000 € à 52 000 € sur 12 mois"),
    ({"libelle": "Mensuel de 2600.0 Euros", "listeComplements": [{"libelle": "Primes"}, {"libelle": "CSE"}]},
     "Mensuel de 2 600 € · Primes, CSE"),
    # La même borne deux fois n'est pas une fourchette.
    ({"libelle": "Annuel de 55000.0 Euros à 55000.0 Euros sur 12 mois"}, "Annuel de 55 000 € sur 12 mois"),
    ({"commentaire": "Selon grille de salaire"}, "Selon grille de salaire"),
    # France Travail recopie parfois le commentaire dans le libellé.
    ({"libelle": "Mensuel de 1133.0 Euros - prime comprise", "commentaire": "Prime comprise"},
     "Mensuel de 1 133 € - prime comprise"),
])
def test_le_salaire_de_france_travail_est_rendu_lisible(salaire, attendu):
    assert apercu.salaire(_offre(source="france_travail", raw={"salaire": salaire})) == attendu


@pytest.mark.parametrize("remuneration, attendu", [
    ({"min": 35000, "max": 45000, "type": "ANNUEL"}, "35 000 – 45 000 € par an"),
    ({"min": 37000, "max": 37000, "type": "ANNUEL"}, "37 000 € par an"),
    ({"min": 0, "max": 2600, "type": "MENSUEL"}, "jusqu'à 2 600 € par mois"),
    ({"min": 0, "max": 0, "type": "ANNUEL"}, ""),
])
def test_la_fourchette_de_dogfinance(remuneration, attendu):
    assert apercu.salaire(_offre(raw={"remuneration": remuneration})) == attendu


def test_l_indemnite_d_un_vie_est_mensuelle():
    assert apercu.salaire(_offre(raw={"indemnite": 3030.57})) == "Indemnité V.I.E : 3 031 € par mois"


def test_une_estimation_d_adzuna_n_est_pas_un_salaire_annonce():
    estime = _offre(raw={"salary_min": 41000, "salary_max": 41000, "salary_is_predicted": "1"})
    annonce = _offre(raw={"salary_min": 25000, "salary_max": 27000, "salary_is_predicted": "0"})
    assert apercu.salaire(estime) == ""
    # Adzuna ne dit pas la monnaie, et couvre dix-neuf pays : pas de symbole.
    assert apercu.salaire(annonce) == "25 000 – 27 000 (monnaie du pays, d'après Adzuna)"


# --- Le salaire que le texte dit ---------------------------------------------

@pytest.mark.parametrize("texte, attendu", [
    ("Profil : Bac+5.\nRémunération : 42-52K€ selon profil et expérience, avec marge de négociation.",
     "Rémunération : 42-52K€ selon profil et expérience"),
    ("La rémunération proposée se situe entre 35 000€ et 45 000€ brut annuel. Poste à Lyon.",
     "rémunération proposée se situe entre 35 000€ et 45 000€ brut annuel"),
    # Une annonce d'un seul bloc : on s'arrête au montant, la suite parle d'autre chose.
    ("Join us. Salary: £25,000 - £27,000 Huge Small Victories We are the highest rated provider",
     "Salary: £25,000 - £27,000"),
    ("Compensation Hourly base pay rate is $22.02 - $33.08/hour. Benefits include dental.",
     "Compensation Hourly base pay rate is $22.02 - $33.08/hour"),
])
def test_un_salaire_ecrit_dans_l_annonce_est_repris_tel_quel(texte, attendu):
    assert apercu.salaire(_offre(texte)) == attendu


@pytest.mark.parametrize("texte", [
    "Vous gérez un portefeuille de 300 M€ pour le compte de clients institutionnels.",
    "Le groupe réalise un chiffre d'affaires de 2 milliards € et verse un salaire attractif.",
    "Rémunération attractive selon profil.",
    "Budget de 50 000 € à piloter.",
])
def test_un_montant_qui_n_est_pas_un_salaire_n_en_devient_pas_un(texte):
    assert apercu.salaire(_offre(texte)) == ""


# --- Les missions ------------------------------------------------------------

def test_la_rubrique_des_missions_est_reprise_en_puces():
    trouvees, points = apercu.missions(_offre(
        "La banque est un acteur majeur du financement.\n"
        "Vos missions :\n"
        "- Suivre les risques de marché ;\n"
        "- Produire les reportings quotidiens\n"
        "Profil recherché :\n"
        "- Bac+5 en finance\n"))
    assert trouvees
    assert points == ["Suivre les risques de marché", "Produire les reportings quotidiens"]


def test_sous_le_titre_la_liste_prime_sur_la_phrase_d_introduction():
    """Mesuré sur France Travail : « Missions principales : », une phrase, un
    sous-titre, puis la vraie liste."""
    _, points = apercu.missions(_offre(
        "Missions principales :\n"
        "Vous intégrerez le pôle Finance, composé d'un responsable et d'un adjoint.\n"
        "Activités :\n"
        "- Suivre les budgets\n"
        "- Assurer la gestion des recettes\n"))
    assert points == ["Suivre les budgets", "Assurer la gestion des recettes"]


def test_sans_rubrique_la_premiere_liste_est_celle_des_missions():
    """Mesuré sur DogFinance : une introduction, la liste des missions, puis
    celle du profil — sans aucun titre."""
    trouvees, points = apercu.missions(_offre(
        "Manpower recherche pour son client un Trésorier (H/F) dans le cadre d'un CDI à Lyon.\n"
        "1. Gestion quotidienne de trésorerie\n"
        "- Suivi des positions bancaires.\n"
        "- Arbitrages de trésorerie.\n"
        "Poste à pourvoir en CDI, salaire selon expérience, rattaché au directeur financier du groupe.\n"
        "- Excel avancé\n"))
    assert trouvees
    assert points == ["Gestion quotidienne de trésorerie", "Suivi des positions bancaires.",
                      "Arbitrages de trésorerie."]


def test_une_liste_rangee_sous_profil_n_est_pas_prise_pour_des_missions():
    trouvees, _ = apercu.missions(_offre(
        "Nous recrutons un analyste pour notre équipe de Paris, au sein de la direction des risques.\n"
        "Profil recherché :\n"
        "- Bac+5 en finance\n"
        "- Anglais courant\n"))
    assert not trouvees


def test_des_puces_ecrites_sur_une_ligne_redeviennent_des_puces():
    _, points = apercu.missions(_offre(
        "Vos missions : * Contrôler les actes de gestion * Traiter les opérations sensibles"))
    assert points == ["Contrôler les actes de gestion", "Traiter les opérations sensibles"]


def test_une_phrase_qui_commence_par_le_poste_n_est_pas_un_titre():
    trouvees, _ = apercu.missions(_offre("Le poste est basé à Paris.\nNotre société existe depuis 1990."))
    assert not trouvees


def test_les_missions_donnees_a_part_par_la_source_sont_preferees_a_la_description():
    _, points = apercu.missions(_offre(
        "Description générale de l'entreprise.",
        raw={"missionDescription": "Responsibilities:\n• Monitor market trends\n• Assist traders\n"
                                   "Candidate profile\n• Master's degree"}))
    assert points == ["Monitor market trends", "Assist traders"]


def test_cinq_missions_au_plus_et_aucune_trop_longue():
    lignes = "\n".join(f"- Mission numéro {n} " + "très détaillée " * 20 for n in range(9))
    _, points = apercu.missions(_offre("Missions :\n" + lignes))
    assert len(points) == apercu.MAX_MISSIONS
    assert all(len(p) <= apercu.LONGUEUR_MISSION + 1 and p.endswith("…") for p in points)


def test_sans_missions_reperables_l_alerte_donne_un_extrait_et_le_dit():
    """Adzuna : cinq cents caractères d'un seul bloc. On commence là où
    l'annonce commence à parler du poste."""
    offre = _offre("Position: Mid Risk Analyst Employment Type: Full-time About the Role: The Risk Analyst "
                   "will own day-to-day monitoring and configuration of trade risk, and manage relationships.")
    trouvees, points = apercu.missions(offre)
    assert not trouvees and points[0].startswith("The Risk Analyst will own")
    assert "📋 Extrait de l'annonce" in apercu.apercu(offre)


def test_une_annonce_en_html_est_lue_sans_ses_balises():
    _, points = apercu.missions(_offre(
        "<p>Vos missions&nbsp;:</p><ul><li>Suivre les <b>risques</b></li><li>Produire les reportings</li></ul>"))
    assert points == ["Suivre les risques", "Produire les reportings"]


def test_l_apercu_dit_quand_le_salaire_n_est_pas_indique():
    texte = apercu.apercu(_offre("Missions :\n- Suivre les risques\n- Produire les reportings"))
    assert texte.splitlines() == ["💶 Salaire non indiqué", "📋 Missions", "• Suivre les risques",
                                  "• Produire les reportings"]


# --- Dans l'alerte -----------------------------------------------------------

@pytest.fixture
def envois(monkeypatch):
    recus = []

    def faux_post(url, json=None, content=None, **kw):
        recus.append((url, json if json is not None else content))
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", faux_post)
    return recus


def _offre_verte(session):
    from app.services.acces import proprietaire

    proprietaire(session)
    ajouter_offre(session, source="france_travail", source_id="1", hash="h1", titre="Analyste risques",
                  entreprise="Banque", score=95, ajoutee_le=maintenant() - timedelta(minutes=5),
                  description_brute="Vos missions :\n- Suivre les risques\n- Produire les reportings",
                  raw={"salaire": {"libelle": "Annuel de 45000.0 Euros à 52000.0 Euros sur 12 mois"}})
    session.commit()


def test_l_alerte_telegram_porte_le_salaire_et_les_missions(session, envois, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:jeton-de-test")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "4242")
    _offre_verte(session)
    assert notification.alerter(session, maintenant() - timedelta(hours=1)) == 1
    texte = envois[0][1]["text"]
    assert texte.startswith("💼 95 · Analyste risques")
    assert "💶 Annuel de 45 000 € à 52 000 € sur 12 mois" in texte
    assert "• Suivre les risques" in texte and "• Produire les reportings" in texte


def test_l_alerte_ntfy_reste_courte(session, envois, monkeypatch):
    """Une notification ntfy est une ligne sur l'écran verrouillé, pas une fiche."""
    monkeypatch.setenv("NTFY_SUJET", "sujet-de-test")
    _offre_verte(session)
    assert notification.alerter(session, maintenant() - timedelta(hours=1)) == 1
    corps = envois[0][1].decode("utf-8")
    assert "Missions" not in corps and "💶" not in corps
