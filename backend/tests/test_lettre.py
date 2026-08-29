"""Le garde-fou anti-invention.

Exigence explicite du projet : « Le LLM ne doit jamais inventer une expérience,
un diplôme ou une compétence absente du profil. » Un prompt ne garantit rien —
surtout avec un modèle local. C'est ce contrôle-ci qui garantit.
"""

import pytest

from app.documents.lettre import (
    MOTS_MIN,
    PROMPT_SYSTEME,
    entites_suspectes,
    nettoyer,
    rediger,
)
from app.models import Offer, Profile


@pytest.fixture
def profil():
    return Profile(
        prenom="Maxime", nom="Nicolas", ville="Paris", pays="France",
        titre_vise="Analyste financier",
        skills=[{"nom": "Analyse financière", "ancree": True}],
        langues=[{"code": "fr", "libelle": "Français", "niveau": "natif"}],
        experiences=[{"entreprise": "Crédit Mutuel", "poste": "Gestionnaire de portefeuille",
                      "debut": "2023-09", "fin": "2025-09",
                      "description": "Suivi des créances export."}],
        formations=[{"etablissement": "EM Normandie", "diplome": "Master 2 Finance",
                     "annee": "2020-2025"}],
    )


@pytest.fixture
def offre():
    return Offer(source="test", source_id="1", titre="Analyste risques de crédit",
                 entreprise="Banque Exemple", lieu="Paris", pays="France",
                 type_contrat="CDI",
                 description_brute="Vous évaluez la solvabilité des contreparties.")


def _lettre(corps: str) -> str:
    """Étoffe un texte pour qu'il atteigne la longueur minimale attendue."""
    return corps + " " + ("Ce point me semble déterminant pour le poste. " * 20)


# --- Détection --------------------------------------------------------------


def test_une_lettre_fidele_ne_declenche_rien(profil, offre):
    texte = ("Mon passage au Crédit Mutuel m'a formé au suivi des créances export. "
             "Mon Master 2 Finance à l'EM Normandie complète ce parcours.")
    assert entites_suspectes(texte, profil, offre) == []


def test_une_entreprise_absente_du_profil_est_detectee(profil, offre):
    """LE test du cahier des charges."""
    texte = "J'ai travaillé chez Goldman Sachs avant de rejoindre le Crédit Mutuel."
    assert "Goldman" in entites_suspectes(texte, profil, offre)


def test_une_ecole_inventee_est_detectee(profil, offre):
    """Le cas réellement observé avec un modèle local."""
    texte = "En tant qu'étudiant à l'Université Paris, j'ai suivi ce cursus."
    assert "Université" in entites_suspectes(texte, profil, offre)


def test_une_date_inventee_est_detectee(profil, offre):
    """Une disponibilité annoncée est une invention comme une autre."""
    assert "2031" in entites_suspectes("Je serai disponible en mars 2031.", profil, offre)


def test_une_annee_du_profil_ne_declenche_rien(profil, offre):
    assert entites_suspectes("Mon poste s'est achevé en 2025.", profil, offre) == []


def test_l_entreprise_de_l_offre_est_autorisee(profil, offre):
    assert entites_suspectes("Rejoindre Banque Exemple m'intéresse.", profil, offre) == []


def test_un_mot_en_debut_de_phrase_n_est_pas_suspect(profil, offre):
    """Sa majuscule est grammaticale : la signaler noierait les vraies alertes."""
    assert entites_suspectes("Analyste est le métier visé. Voilà.", profil, offre) == []


def test_la_ponctuation_finale_ne_cree_pas_de_faux_positif(profil, offre):
    assert entites_suspectes("J'ai postulé chez Banque Exemple. Puis ailleurs.",
                             profil, offre) == []


# --- Nettoyage --------------------------------------------------------------


def test_les_formules_ajoutees_par_le_modele_sont_retirees():
    brut = ("Madame, Monsieur,\n\nMon parcours parle de lui-même.\n\n"
            "Cordialement,\nMaxime Nicolas")
    assert nettoyer(brut) == "Mon parcours parle de lui-même."


# --- Boucle de rédaction ----------------------------------------------------


def test_une_lettre_inventee_est_rejetee_puis_regeneree(profil, offre):
    """Rejeter et régénérer, pas seulement avertir."""
    reponses = [
        _lettre("J'ai travaillé chez Goldman Sachs."),          # invention
        _lettre("Mon passage au Crédit Mutuel m'a formé."),     # honnête
    ]
    appels = []

    def faux_modele(systeme, message):
        appels.append(systeme)
        return reponses.pop(0)

    lettre, compte_rendu = rediger(profil, offre, faux_modele, tentatives=3)

    assert compte_rendu["essais"] == 2
    assert "Goldman" not in lettre
    # La seconde consigne nomme l'erreur à corriger.
    assert "Goldman" in appels[1]


def test_l_echec_persistant_ne_livre_pas_une_lettre_mensongere(profil, offre):
    """Mieux vaut pas de lettre qu'une lettre qui ment sur le parcours."""
    def modele_incorrigible(systeme, message):
        return _lettre("J'ai dirigé le fonds Bridgewater pendant dix ans.")

    with pytest.raises(ValueError, match="Bridgewater"):
        rediger(profil, offre, modele_incorrigible, tentatives=2)


def test_une_lettre_trop_courte_est_refusee(profil, offre):
    def modele_bavard_comme_un_sms(systeme, message):
        return "Bonjour, je postule."

    with pytest.raises(ValueError, match="longueur"):
        rediger(profil, offre, modele_bavard_comme_un_sms, tentatives=1)


def test_le_prompt_porte_la_contrainte_anti_invention():
    """Garde-fou du garde-fou : cette consigne ne doit pas disparaître."""
    assert "TU N'INVENTES RIEN" in PROMPT_SYSTEME
    assert "date de\n  disponibilité" in PROMPT_SYSTEME or "disponibilité" in PROMPT_SYSTEME


def test_la_longueur_minimale_reste_raisonnable():
    assert 50 <= MOTS_MIN <= 150
