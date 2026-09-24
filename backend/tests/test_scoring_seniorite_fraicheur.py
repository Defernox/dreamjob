"""Le niveau du poste et la fraîcheur de l'annonce.

Ce que ces tests protègent avant tout : **ni l'un ni l'autre ne doit pénaliser
une offre qu'il ne sait pas juger**, le niveau ne doit jamais faire monter un
poste (il ne fait que retirer), et la fraîcheur ne doit jamais porter un score
à elle seule.
"""

from datetime import datetime, timedelta

import pytest

from app.config import PoidsScoring
from app.models import Offer, Profile
from app.models.base import maintenant
from app.scoring.cible import construire
from app.scoring.explain import expliquer
from app.scoring.extraction import extraire
from app.scoring.score import (
    FRAICHEUR_NULLE_JOURS,
    FRAICHEUR_PLEINE_JOURS,
    Resultat,
    calculer,
    score_fraicheur,
    score_seniorite,
)

from .test_scoring import offre, profil

# L'horloge réelle, et non une date figée : `calculer` mesure la fraîcheur par
# rapport à aujourd'hui. Figé au 30 août 2026, ce repère a fait tomber trois
# tests vingt-cinq jours plus tard.
LE_JOUR_J = maintenant()


def _il_y_a(jours: int) -> datetime:
    return LE_JOUR_J - timedelta(days=jours)


def _niveau(annees: int, **kw) -> float | None:
    o = offre(**kw)
    return score_seniorite(construire(profil(annees_experience=annees), []), extraire(o),
                           Resultat(0))


# --- Niveau du poste -----------------------------------------------------------


def test_sans_anciennete_renseignee_le_critere_ne_se_prononce_pas():
    """Le champ vaut 0 tant que l'utilisateur ne l'a pas saisi. Le noter zéro
    reviendrait à traiter tout le monde comme un débutant."""
    assert _niveau(0, titre="Analyste senior") is None


@pytest.mark.parametrize("titre, attendu", [
    ("Analyste risques", 100.0),                          # intermédiaire, comme le profil
    ("Analyste junior", 90.0),                            # un cran en dessous : accessible
    ("Analyste senior", 65.0),                            # un cran au-dessus
    ("Responsable des risques", 30.0),                    # encadrement
    ("Directeur des risques", 5.0),                       # direction : hors de portée
])
def test_le_niveau_de_l_intitule_face_a_trois_ans(titre, attendu):
    assert _niveau(3, titre=titre) == attendu


def test_les_annees_chiffrees_priment_sur_l_intitule():
    """« Junior » dans un intitulé qui réclame ensuite huit ans : c'est le
    chiffre qui filtrera la candidature, pas l'étiquette."""
    assert _niveau(3, titre="Analyste junior",
                   description_brute="Vous justifiez de 8 ans d'expérience minimum.") == 20.0


@pytest.mark.parametrize("exigees, attendu", [
    (2, 100.0),      # moins que ce qu'on a
    (4, 100.0),      # un an de plus : ne ferme aucune porte
    (9, 0.0),        # six de plus : rédhibitoire
])
def test_l_ecart_d_annees_se_lit_par_paliers(exigees, attendu):
    assert _niveau(3, description_brute=f"Vous avez {exigees} ans d'expérience en finance.") \
        == attendu


def test_une_fourchette_se_lit_par_son_plancher():
    """« 3 à 5 ans » ouvre la porte à trois ans."""
    assert _niveau(3, description_brute="Expérience de 3 à 5 ans en risques.") == 100.0


def test_l_anciennete_de_l_entreprise_n_est_pas_une_exigence():
    """« Fort de 30 ans d'expérience » parle de la société, pas du candidat."""
    assert _niveau(3, description_brute="Cabinet fort de 30 ans d'expérience.") == 100.0


def test_un_grade_bancaire_n_est_pas_un_poste_de_direction():
    """Un « Assistant Vice President » a quelques années d'expérience."""
    assert _niveau(6, titre="Middle Office Analyst (Assistant Vice President)") == 100.0


# --- Fraîcheur ---------------------------------------------------------------------


def test_une_offre_du_jour_vaut_le_maximum():
    assert score_fraicheur(offre(date_publication=LE_JOUR_J), LE_JOUR_J) == 100.0


def test_une_offre_de_la_semaine_vaut_encore_le_maximum():
    o = offre(date_publication=_il_y_a(FRAICHEUR_PLEINE_JOURS))
    assert score_fraicheur(o, LE_JOUR_J) == 100.0


def test_une_offre_de_plus_de_quatre_mois_ne_vaut_plus_rien():
    o = offre(date_publication=_il_y_a(FRAICHEUR_NULLE_JOURS + 300))
    assert score_fraicheur(o, LE_JOUR_J) == 0.0


def test_la_decroissance_est_continue_et_non_par_paliers():
    notes = [score_fraicheur(offre(date_publication=_il_y_a(j)), LE_JOUR_J)
             for j in range(20, 50)]
    assert len(set(notes)) == 30
    assert notes == sorted(notes, reverse=True)


def test_sans_date_de_publication_on_se_rabat_sur_la_recuperation():
    o = offre(date_publication=None, date_recuperation=_il_y_a(0))
    assert score_fraicheur(o, LE_JOUR_J) == 100.0


def test_sans_aucune_date_le_critere_se_tait():
    o = Offer(source="t", source_id="1", titre="Analyste", date_recuperation=None)
    assert score_fraicheur(o, LE_JOUR_J) is None


def test_une_date_future_ne_produit_pas_de_note_au_dessus_de_cent():
    assert score_fraicheur(offre(date_publication=_il_y_a(-30)), LE_JOUR_J) == 100.0


# --- L'articulation avec le reste du score -----------------------------------------


def test_la_fraicheur_seule_ne_fait_pas_un_score():
    """Un profil qui ne permet de juger ni le métier ni le contenu ne sort pas
    un score de la seule fraîcheur."""
    vide = Profile()
    o = offre(date_publication=LE_JOUR_J)
    assert calculer(vide, o, extraire(o), PoidsScoring(), construire(vide, [])).score == 0.0


def test_deux_offres_identiques_sont_departagees_par_leur_age():
    recente = offre(source_id="a", date_publication=_il_y_a(1))
    ancienne = offre(source_id="b", date_publication=_il_y_a(90))
    p = profil()
    cible = construire(p, [])
    a = calculer(p, recente, extraire(recente), PoidsScoring(), cible).score
    b = calculer(p, ancienne, extraire(ancienne), PoidsScoring(), cible).score
    assert a > b


@pytest.mark.parametrize("jours, attendu", [
    (2, "cette semaine"),
    (9, "ce mois-ci"),          # notée 99 : la phrase ne doit pas la dégrader
    (60, "plus d'un mois"),
    (100, "ancienne"),
    (400, "probablement close"),
])
def test_la_phrase_suit_la_barre(jours, attendu):
    o = offre(date_publication=_il_y_a(jours))
    p = profil()
    s = extraire(o)
    texte = expliquer(calculer(p, o, s, PoidsScoring(), construire(p, [])), p, o, s)
    assert attendu in texte, texte
