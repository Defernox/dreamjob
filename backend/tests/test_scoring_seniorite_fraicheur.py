"""Les deux critères ajoutés pour départager les offres.

Le score les a acquis pour une raison mesurée : sur 2 490 offres, 252 se
partageaient la même note. La fraîcheur est renseignée à 100 % et s'étale sur
1 072 jours, la séniorité couvre une offre sur cinq — ce sont les deux seuls
signaux disponibles capables de trancher.

Ce que ces tests protègent avant tout : **ni l'un ni l'autre ne doit pénaliser
une offre qu'il ne sait pas juger**, et la fraîcheur ne doit jamais porter un
score à elle seule.
"""

from datetime import datetime, timedelta

import pytest

from app.config import PoidsScoring
from app.models import Offer, Profile
from app.models.base import maintenant
from app.scoring.explain import expliquer
from app.scoring.extraction import extraire
from app.scoring.score import (
    ANNEES_JUNIOR,
    FRAICHEUR_NULLE_JOURS,
    FRAICHEUR_PLEINE_JOURS,
    SENIORITE_VOCABULAIRE_CONTRE,
    calculer,
    score_fraicheur,
    score_seniorite,
)

from .test_scoring import offre, profil

# L'horloge réelle, et non une date figée : `calculer` mesure la fraîcheur par
# rapport à aujourd'hui. Figé au 30 août 2026, ce repère a fait tomber trois
# tests vingt-cinq jours plus tard — l'annonce « d'il y a deux jours » en avait
# alors vingt-sept. Les tests qui appellent `score_fraicheur` directement lui
# passent ce même repère, ils restent donc exacts.
LE_JOUR_J = maintenant()


def _il_y_a(jours: int) -> datetime:
    return LE_JOUR_J - timedelta(days=jours)


# --- Séniorité ---------------------------------------------------------------


def test_sans_anciennete_renseignee_le_critere_ne_se_prononce_pas():
    """Le champ vaut 0 tant que l'utilisateur ne l'a pas saisi. Le noter zéro
    reviendrait à traiter tout le monde comme un débutant."""
    assert score_seniorite(profil(annees_experience=0),
                           offre(titre="Analyste senior")) is None


def test_les_annees_chiffrees_priment_sur_le_vocabulaire():
    """« Junior » dans un intitulé qui réclame ensuite huit ans : c'est le
    chiffre qui filtrera la candidature, pas l'étiquette."""
    p = profil(annees_experience=3)
    o = offre(titre="Analyste junior (H/F)",
              description_brute="Vous justifiez de 8 ans d'expérience minimum.")
    # Sur le seul vocabulaire, ce profil junior aurait obtenu 100.
    assert score_seniorite(p, offre(titre="Analyste junior (H/F)")) == 100.0
    assert score_seniorite(p, o) == 20.0


@pytest.mark.parametrize("exigees, attendu", [
    (2, 100.0),      # moins que ce qu'on a
    (3, 100.0),      # pile
    (4, 100.0),      # un an de plus : ne ferme aucune porte
    (9, 0.0),        # six de plus : rédhibitoire
    (12, 0.0),
])
def test_l_ecart_d_annees_se_lit_par_paliers(exigees, attendu):
    o = offre(description_brute=f"Vous avez {exigees} ans d'expérience en finance.")
    assert score_seniorite(profil(annees_experience=3), o) == attendu


def test_entre_les_deux_bornes_la_note_decroit():
    p = profil(annees_experience=3)
    notes = [score_seniorite(p, offre(description_brute=f"{n} ans d'expérience exigés"))
             for n in (5, 6, 7)]
    assert notes == sorted(notes, reverse=True), notes
    assert all(0 < n < 100 for n in notes), notes


def test_la_plus_forte_exigence_decide():
    """Une annonce peut citer plusieurs durées ; c'est la plus dure qui filtre."""
    o = offre(description_brute="2 ans d'expérience en audit, 10 ans d'expérience en risques.")
    assert score_seniorite(profil(annees_experience=3), o) == 0.0


def test_un_poste_senior_penalise_un_profil_junior_sans_l_ecarter():
    """Les intitulés mentent souvent : on pénalise, on n'exclut pas."""
    note = score_seniorite(profil(annees_experience=2), offre(titre="Analyste senior (H/F)"))
    assert note == SENIORITE_VOCABULAIRE_CONTRE
    assert 0 < note < 100


def test_le_meme_poste_convient_a_un_profil_experimente():
    assert score_seniorite(profil(annees_experience=ANNEES_JUNIOR + 3),
                           offre(titre="Analyste senior (H/F)")) == 100.0


def test_une_offre_junior_convient_a_un_profil_junior():
    assert score_seniorite(profil(annees_experience=2),
                           offre(titre="Analyste junior (H/F)")) == 100.0


def test_une_offre_muette_sur_l_anciennete_n_est_pas_jugee():
    """Aucun chiffre, aucun mot-clé : le critère se tait et son poids part
    ailleurs. C'est le cas le plus fréquent — quatre offres sur cinq."""
    o = offre(titre="Analyste credit (H/F)", description_brute="Vous suivez les encours.")
    assert score_seniorite(profil(annees_experience=3), o) is None


def test_les_marqueurs_ne_matchent_pas_a_l_interieur_d_un_mot():
    """Une frontière de mot ecrite dans une chaine non brute vaut BACKSPACE :
    les motifs n'attrapaient plus rien, en silence. Ce test le rend visible."""
    o = offre(titre="Analyste (H/F)", description_brute="Poste base a Seniorville.")
    assert score_seniorite(profil(annees_experience=2), o) is None
    o2 = offre(titre="Analyste (H/F)", description_brute="Un poste senior est a pourvoir.")
    assert score_seniorite(profil(annees_experience=2), o2) is not None


# --- Fraîcheur ---------------------------------------------------------------


def test_une_offre_du_jour_vaut_le_maximum():
    assert score_fraicheur(offre(date_publication=LE_JOUR_J), LE_JOUR_J) == 100.0


def test_une_offre_de_la_semaine_vaut_encore_le_maximum():
    o = offre(date_publication=_il_y_a(FRAICHEUR_PLEINE_JOURS))
    assert score_fraicheur(o, LE_JOUR_J) == 100.0


def test_une_offre_de_plus_de_quatre_mois_ne_vaut_plus_rien():
    o = offre(date_publication=_il_y_a(FRAICHEUR_NULLE_JOURS + 300))
    assert score_fraicheur(o, LE_JOUR_J) == 0.0


def test_la_decroissance_est_continue_et_non_par_paliers():
    """C'est tout l'intérêt du critère : des paliers recréeraient les égalités
    qu'on cherche à défaire. Trente jours consécutifs, trente notes."""
    notes = [score_fraicheur(offre(date_publication=_il_y_a(j)), LE_JOUR_J)
             for j in range(20, 50)]
    assert len(set(notes)) == 30
    assert notes == sorted(notes, reverse=True)


def test_sans_date_de_publication_on_se_rabat_sur_la_recuperation():
    """Plusieurs sources ne datent pas leurs annonces ; la date à laquelle on
    l'a vue passer reste un majorant honnête de son âge."""
    o = offre(date_publication=None, date_recuperation=_il_y_a(0))
    assert score_fraicheur(o, LE_JOUR_J) == 100.0


def test_sans_aucune_date_le_critere_se_tait():
    o = Offer(source="t", source_id="1", titre="Analyste", date_recuperation=None)
    assert score_fraicheur(o, LE_JOUR_J) is None


def test_une_date_future_ne_produit_pas_de_note_au_dessus_de_cent():
    """Une source mal réglée peut publier daté de demain."""
    assert score_fraicheur(offre(date_publication=_il_y_a(-30)), LE_JOUR_J) == 100.0


# --- L'articulation avec le reste du score -----------------------------------


def test_la_fraicheur_seule_ne_fait_pas_un_score():
    """Le piège du critère toujours évaluable : sur un profil qui ne permet de
    juger aucun critère de fond, la redistribution des poids lui donnait la
    totalité et sortait 100 sur une offre que personne n'a pu évaluer."""
    vide = Profile(annees_experience=0)
    o = offre(date_publication=LE_JOUR_J)
    assert calculer(vide, o, extraire(o), PoidsScoring(), 100.0).score == 0.0


def test_deux_offres_identiques_sont_departagees_par_leur_age():
    """La raison d'être du critère, en une assertion."""
    recente = offre(source_id="a", date_publication=_il_y_a(1))
    ancienne = offre(source_id="b", date_publication=_il_y_a(90))
    p = profil(annees_experience=3)
    a = calculer(p, recente, extraire(recente), PoidsScoring(), 100.0).score
    b = calculer(p, ancienne, extraire(ancienne), PoidsScoring(), 100.0).score
    assert a > b


def test_les_deux_criteres_apparaissent_dans_l_explication():
    """Un critère qui pèse sur la note sans jamais être nommé est un score
    qu'on ne peut pas contester."""
    o = offre(titre="Analyste senior (H/F)", date_publication=_il_y_a(2))
    p = profil(annees_experience=2)
    texte = expliquer(calculer(p, o, extraire(o), PoidsScoring(), 100.0), p, o, extraire(o))
    assert "séniorité" in texte or "au-dessus" in texte, texte
    assert "publiée" in texte, texte


def test_un_critere_non_evaluable_reste_muet_dans_l_explication():
    """Ne rien dire vaut mieux que d'annoncer « séniorité non évaluée » à
    quelqu'un qui n'a simplement pas rempli le champ."""
    o = offre(titre="Analyste credit (H/F)", date_publication=_il_y_a(2))
    p = profil(annees_experience=0)
    texte = expliquer(calculer(p, o, extraire(o), PoidsScoring(), 100.0), p, o, extraire(o))
    assert "séniorité" not in texte.lower(), texte
    assert " · ·" not in texte, "un séparateur orphelin trahit un fragment vide"


@pytest.mark.parametrize("jours, attendu", [
    (2, "cette semaine"),
    (9, "ce mois-ci"),          # notée 99 : la phrase ne doit pas la dégrader
    (30, "ce mois-ci"),
    (60, "plus d'un mois"),
    (100, "déjà ancienne"),
    (400, "probablement close"),
])
def test_la_phrase_suit_la_barre(jours, attendu):
    """Une annonce de neuf jours est notée 99 ; l'annoncer « ce mois-ci » sous
    une barre pleine faisait douter de l'un ou de l'autre. Les seuils du texte
    sont désormais ceux de la décroissance."""
    o = offre(date_publication=_il_y_a(jours))
    p = profil(annees_experience=3)
    texte = expliquer(calculer(p, o, extraire(o), PoidsScoring(), 100.0), p, o, extraire(o))
    assert attendu in texte, texte
