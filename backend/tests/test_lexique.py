"""Ce sur quoi repose le score : le vocabulaire, les exigences d'une annonce,
le profil de ciblage tiré du CV, et le corpus des offres."""

import pytest

from app.models import Profile
from app.scoring.cible import POIDS_DOMAINE, construire
from app.scoring.corpus import Corpus
from app.scoring.exigences import (
    certifications_exigees,
    niveau_intitule,
    niveaux_etudes,
    statut_public_exige,
)
from app.scoring.extraction import Signaux
from app.scoring.lexique import bigrammes, jetons, jetons_intitule

# --- Le vocabulaire ------------------------------------------------------------------


def test_une_expression_francaise_et_son_equivalent_anglais_se_rencontrent():
    assert bigrammes(jetons("risque de crédit")) == bigrammes(jetons("credit risk"))


def test_pluriels_et_feminins_se_rejoignent():
    assert jetons("financières") == jetons("financier")
    assert jetons("directrice") == jetons("directeur")
    assert jetons("administrative") == jetons("administratif")
    assert jetons("analyste") == jetons("analyst")


def test_un_intitule_perd_ce_qui_ne_dit_pas_le_metier():
    """Contrat, niveau, genre, lieu, écriture inclusive : chacun a son critère."""
    assert jetons_intitule("Gestionnaire middle office junior - CDI - Montpellier (H/F)",
                           "34 - Montpellier") == jetons("gestionnaire middle office")
    assert jetons_intitule("Responsable administratif(ve)") == jetons("responsable administratif")


def test_un_diplome_n_est_pas_un_metier():
    assert jetons_intitule("Master 2 Finance") == jetons("finance")


def test_p_and_l_survit_a_la_normalisation():
    """L'esperluette tombait, et « P&L » avec elle."""
    assert "pnl" in jetons("Suivi du P&L quotidien")


# --- Les exigences d'une annonce ---------------------------------------------------------


@pytest.mark.parametrize("titre, niveau", [
    ("Directeur administratif et financier", "direction"),
    ("Directeur adjoint des finances", "encadrement"),
    ("Adjoint au responsable administratif", "confirme"),
    ("Vice President, Middle Office", "encadrement"),
    ("Analyst (Assistant Vice President)", "confirme"),
    ("Stage trading commodities", "stage"),
    ("VIE Junior Financial Controller", "junior"),
    ("Chargé de middle office", "intermediaire"),
])
def test_le_niveau_se_lit_dans_l_intitule(titre, niveau):
    assert niveau_intitule(titre) == niveau


def test_maitrise_d_excel_n_est_pas_un_diplome():
    """« Maîtrise d'Excel » transformait un poste Bac+2 en Bac+4."""
    assert niveaux_etudes("BTS comptabilité, maîtrise d'Excel") == [2]


def test_une_certification_citee_comme_un_plus_n_est_pas_exigee():
    assert certifications_exigees("Le CFA est un plus.") == []
    assert certifications_exigees("CFA niveau 2 exigé.") == ["CFA"]


def test_un_poste_ouvert_aux_contractuels_n_est_pas_reserve():
    assert statut_public_exige("Recrutement par voie statutaire")
    assert not statut_public_exige("Ouvert aux titulaires et aux contractuels, voie statutaire")


# --- Le profil de ciblage ------------------------------------------------------------------


def _profil(**kw) -> Profile:
    base = dict(
        titre_vise="Finance de marché",
        skills=[{"nom": "Connaissance des produits boursiers", "ancree": True}],
        experiences=[
            {"poste": "Stagiaire crédit", "fin": "2021", "description": "Suivi des créances.",
             "tags": ["Crédit"]},
            {"poste": "Gestionnaire de portefeuille", "fin": "en cours",
             "description": "Gestion d'un portefeuille d'entreprises.", "tags": []},
        ],
    )
    return Profile(**{**base, **kw})


def test_le_poste_le_plus_recent_pese_le_plus():
    cible = construire(_profil(), [])
    poids = {i.libelle: i.poids for i in cible.intitules}
    assert poids["Gestionnaire de portefeuille"] > poids["Stagiaire crédit"]


def test_les_recherches_sont_des_intitules_vises():
    cible = construire(_profil(), [["middle office"]])
    assert any(i.origine == "recherche" and i.libelle == "middle office"
               for i in cible.intitules)


def test_les_mots_creux_d_une_competence_ne_comptent_pas():
    """« Connaissance des produits boursiers » : c'est « boursiers » qui compte."""
    cible = construire(_profil(), [])
    assert cible.poids(jetons("connaissance")[0]) == 0.0
    assert cible.poids(jetons("boursiers")[0]) > 0.0


def test_le_vocabulaire_d_un_domaine_vise_s_ajoute_a_faible_poids():
    """Un junior qui vise la finance de marché n'a pas encore écrit « dérivés »."""
    cible = construire(_profil(), [])
    assert "finance de marché" in cible.domaines
    assert cible.poids(jetons("dérivés")[0]) == POIDS_DOMAINE


def test_un_domaine_non_vise_n_ajoute_rien():
    cible = construire(Profile(titre_vise="Boulanger"), [])
    assert cible.domaines == []
    assert cible.poids(jetons("dérivés")[0]) == 0.0


def test_le_niveau_d_etudes_se_lit_dans_les_diplomes():
    cible = construire(Profile(formations=[{"diplome": "Master 2 Finance"}]), [])
    assert cible.etudes == 5


# --- Le corpus ---------------------------------------------------------------------------------


def test_un_mot_rare_distingue_plus_qu_un_mot_banal():
    signaux = [Signaux(corps={"financ": 1}), Signaux(corps={"financ": 1, "titrisation": 1}),
               Signaux(corps={"financ": 1})]
    corpus = Corpus.depuis(signaux)
    assert corpus.idf_corps("titrisation") > corpus.idf_corps("financ")


def test_le_seuil_d_un_terme_etabli_suit_la_taille_du_corpus():
    """Sur un petit fil, exiger trois annonces viderait tout."""
    petit = Corpus.depuis([Signaux(corps={"titrisation": 1})])
    assert petit.etabli("titrisation", 3)
    grand = Corpus.depuis([Signaux(corps={"titrisation": 1})]
                          + [Signaux(corps={"x": 1})] * 600)
    assert not grand.etabli("titrisation", 3)
