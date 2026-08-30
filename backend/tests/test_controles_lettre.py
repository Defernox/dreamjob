"""Les contrôles ajoutés à la refonte : chiffres, contrat, disponibilité, style.

Chaque test nomme le comportement fautif d'origine — plusieurs viennent de
lettres réellement produites par mistral:7b au cours de la mise au point.
"""

import json

import pytest

from app.documents.controles import (
    bloquantes,
    entites_suspectes,
    chiffres_inventes,
    contrat_incoherent,
    defauts_de_style,
    disponibilite_inventee,
    ouverture_convenue,
    rythme_mecanique,
)
from app.documents.lettre import nettoyer
from app.models import Offer, Profile
from app.scoring.couverture import mots_cles_non_couverts


@pytest.fixture
def profil():
    return Profile(
        prenom="Maxime", nom="Nicolas", ville="Paris", pays="France",
        titre_vise="Analyste financier",
        skills=[{"nom": "Analyse financière", "ancree": True}],
        langues=[{"code": "fr", "libelle": "Français", "niveau": "natif"}],
        experiences=[{
            "entreprise": "Crédit Mutuel", "poste": "Gestionnaire de portefeuille",
            "debut": "2023-09", "fin": "2025-09",
            "description": "Portefeuille de 15 à 25 entreprises, 50 à 75 millions "
                           "d'euros de chiffre d'affaires.",
        }],
        formations=[{"etablissement": "EM Normandie", "diplome": "Master 2 Finance",
                     "annee": "2020-2025", "details": "Mémoire noté 16,75/20."}],
    )


@pytest.fixture
def offre():
    return Offer(source="test", source_id="1", titre="Analyste risques de crédit",
                 entreprise="Banque Exemple", lieu="Paris", pays="France",
                 type_contrat="CDI",
                 description_brute="Vous évaluez la solvabilité des contreparties.")


# --- Chiffres inventés -------------------------------------------------------


def test_un_chiffre_absent_du_profil_est_repere(profil, offre):
    lettre = "J'ai encadré une équipe de 12 personnes sur 4 sites."
    assert "12" in chiffres_inventes(lettre, profil, offre)


def test_les_chiffres_du_profil_passent(profil, offre):
    lettre = ("J'ai géré un portefeuille de 15 à 25 entreprises représentant "
              "50 à 75 millions d'euros.")
    assert chiffres_inventes(lettre, profil, offre) == []


def test_les_milliers_espaces_sont_reconnus(profil, offre):
    """La typographie française espace les milliers : « 50 000 » et « 50000 »
    doivent être le même nombre, sinon toute lettre soignée est refusée."""
    profil.experiences[0]["description"] += " Budget de 50000 euros."
    assert chiffres_inventes("Un budget de 50 000 euros.", profil, offre) == []


def test_la_virgule_decimale_est_reconnue(profil, offre):
    assert chiffres_inventes("Mémoire noté 16,75/20.", profil, offre) == []


def test_les_annees_restent_au_controle_des_noms_propres(profil, offre):
    """Les signaler deux fois embrouillerait le reproche fait au modèle."""
    assert chiffres_inventes("En 1998, j'ai commencé.", profil, offre) == []


# --- Type de contrat ---------------------------------------------------------


def test_parler_d_alternance_sur_une_offre_en_cdi(profil, offre):
    """Mesuré : mistral écrit « alternance » sur une offre CDI. Une lettre qui
    se trompe de contrat est écartée avant même le fond."""
    lettre = "Je recherche une alternance dans votre équipe."
    assert "alternance" in contrat_incoherent(lettre, profil, offre)


def test_un_contrat_du_parcours_reste_mentionnable(profil, offre):
    """« Durant mon stage chez X » reste vrai même si l'offre porte sur un CDI."""
    profil.experiences[0]["description"] += " Stage de fin d'études."
    lettre = "Durant mon stage, j'ai suivi des créances export."
    assert contrat_incoherent(lettre, profil, offre) == []


def test_une_offre_sans_contrat_ne_declenche_rien(profil, offre):
    offre.type_contrat = ""
    assert contrat_incoherent("Une alternance m'intéresse.", profil, offre) == []


# --- Disponibilité -----------------------------------------------------------


def test_une_date_annoncee_sans_profil_est_reperee(profil):
    """Le profil n'en donne aucune : promettre une date est une invention."""
    assert disponibilite_inventee("Je suis disponible immédiatement.", profil)


def test_une_disponibilite_renseignee_autorise_l_annonce(profil):
    profil.disponibilite = "Immédiate"
    assert disponibilite_inventee("Je suis disponible immédiatement.", profil) == []


def test_se_dire_disponible_pour_echanger_reste_permis(profil):
    """« Je suis disponible pour en discuter » est une clôture normale, pas un
    engagement. L'inclure faisait rejeter toutes les lettres."""
    assert disponibilite_inventee("Je suis disponible pour en discuter.", profil) == []


# --- Ouverture et rythme -----------------------------------------------------


@pytest.mark.parametrize("debut", [
    "C'est avec un grand intérêt que je postule.",
    "Fort de mon expérience, je vous écris.",
    "Actuellement en poste, je cherche.",
    "Suite à votre annonce, je me permets.",
])
def test_les_ouvertures_convenues_sont_reperees(debut):
    assert ouverture_convenue(debut)


def test_une_ouverture_factuelle_passe():
    assert ouverture_convenue("Gestionnaire de portefeuille export, je postule.") == []


def test_un_paragraphe_sans_phrase_courte_est_signale():
    long = ("Cette phrase compte largement plus de douze mots afin de démontrer "
            "le comportement du contrôle de rythme mis en place.")
    assert rythme_mecanique(long)


def test_une_phrase_breve_suffit_a_casser_le_rythme():
    texte = ("Cette phrase compte largement plus de douze mots pour les besoins "
             "de ce test précis. Ce poste m'intéresse.")
    assert rythme_mecanique(texte) == []


# --- Le nettoyage ------------------------------------------------------------


@pytest.mark.parametrize("appel", [
    "Bonjour,", "Madame, Monsieur,", "Mon cher directeur,",
    "Salutations cher recruteur,",
])
def test_les_formules_d_appel_inventees_sont_retirees(appel, profil):
    """Le document en pose une lui-même : les deux se retrouvaient l'une sous
    l'autre. « Mon cher directeur » passait au travers."""
    lettre = f"{appel}\n\nLe poste m'intéresse. Mon parcours y répond."
    assert appel.rstrip(",") not in nettoyer(lettre, profil)


def test_la_signature_du_modele_est_retiree(profil):
    """Le document signe déjà. Le modèle signait par-dessus."""
    lettre = "Le poste m'intéresse.\n\nMaxime Nicolas"
    assert "Maxime Nicolas" not in nettoyer(lettre, profil)


def test_sans_profil_le_nettoyage_reste_possible():
    """`nettoyer` est appelé sans profil dans les tests existants."""
    assert nettoyer("Bonjour,\n\nLe poste m'intéresse.") == "Le poste m'intéresse."


# --- Les deux familles -------------------------------------------------------


def test_le_perroquet_n_est_pas_bloquant(profil, offre):
    """Il ne distingue pas « j'ai fait X » de « je ferais X » : le rendre
    bloquant refusait deux offres réelles sur deux."""
    assert "copies" not in bloquantes("peu importe", profil, offre)
    assert "copies" in defauts_de_style("peu importe", profil, offre)


def test_l_invention_reste_bloquante(profil, offre):
    assert "inventions" in bloquantes("peu importe", profil, offre)
    assert "chiffres" in bloquantes("peu importe", profil, offre)


# --- Mots-clés non couverts --------------------------------------------------


def test_les_termes_recurrents_absents_du_profil_ressortent(profil, offre):
    offre.description_brute = (
        "Vous produisez des reportings réglementaires. Les reportings sont "
        "quotidiens. Le provisionnement et les reportings occupent le poste, "
        "avec du provisionnement mensuel et un provisionnement annuel."
    )
    manquants = mots_cles_non_couverts(profil, offre)
    assert "reportings" in manquants
    assert "provisionnement" in manquants


def test_un_terme_couvert_par_un_synonyme_ne_ressort_pas(profil, offre):
    """Le profil dit « Analyse financière » : « analysis » n'est pas manquant."""
    offre.description_brute = "analysis analysis analysis des dossiers."
    assert "analysis" not in mots_cles_non_couverts(profil, offre)


def test_les_verbes_d_annonce_sont_ecartes(profil, offre):
    """« Vous assurez », « vous accompagnez » : de la rédaction, pas des
    compétences."""
    offre.description_brute = ("Vous assurez le suivi. Vous assurez la relation. "
                               "Vous assurez le reporting quotidien assurez.")
    assert "assurez" not in mots_cles_non_couverts(profil, offre)


def test_un_profil_vide_ne_reclame_rien(offre):
    assert mots_cles_non_couverts(Profile(), offre) == []


# --- Le journal de génération ------------------------------------------------


def test_le_journal_de_generation_est_ecrit(profil, offre, tmp_path):
    """Quand une lettre est mauvaise, c'est le seul moyen de savoir quelle
    étape a fauté."""
    from app.documents.dossier import generer

    modele = Path_modele()
    resultat = generer(
        profil, offre, tmp_path, modele,
        redacteur=lambda s, m: "Le poste m'intéresse. " * 40,
        tentatives_lettre=1, ouvrir_apres=False,
    )
    journal = resultat.dossier / "generation.json"
    assert journal.exists()
    donnees = json.loads(journal.read_text(encoding="utf-8"))
    assert "lettre" in donnees
    assert "mots_cles_non_couverts" in donnees


def Path_modele():
    """Le modèle Word réel du projet — les tests de documents s'en servent."""
    from pathlib import Path

    return Path(__file__).resolve().parents[2] / "templates" / "cv_modele.docx"


# --- Noms d'entreprise ponctués ---------------------------------------------


def test_un_nom_d_entreprise_ponctue_est_reconnu(profil, offre):
    """Mesuré sur une offre réelle : « UQPAY PTE. LTD. » faisait refuser la
    lettre trois fois de suite, pour avoir cité l'employeur.

    Le vocabulaire autorisé était découpé par `normaliser().split()`, qui garde
    le point final, alors que la lettre l'est par `mots()`, qui le retire :
    « pte » n'était jamais trouvé dans un vocabulaire contenant « pte. ».
    """
    offre.entreprise = "UQPAY PTE. LTD."
    lettre = "Le poste chez UQPAY PTE. LTD. correspond à mon parcours."
    assert entites_suspectes(lettre, profil, offre) == []


@pytest.mark.parametrize("raison_sociale", [
    "Société Générale S.A.", "Acme Inc.", "Dupont & Co.", "Groupe X S.A.S.",
])
def test_les_formes_juridiques_ponctuees_passent(profil, offre, raison_sociale):
    offre.entreprise = raison_sociale
    assert entites_suspectes(f"Ma candidature chez {raison_sociale}.", profil, offre) == []


def test_une_entreprise_vraiment_absente_reste_signalee(profil, offre):
    """Le correctif ne doit pas ouvrir la porte : ce qui n'est nulle part
    reste une invention."""
    # La fonction rapporte le mot tel qu'il apparaît, ponctuation comprise :
    # c'est ce qui sera cité au modèle, et il doit pouvoir le retrouver.
    suspects = entites_suspectes("J'ai travaillé chez Danone.", profil, offre)
    assert any("Danone" in s for s in suspects)
