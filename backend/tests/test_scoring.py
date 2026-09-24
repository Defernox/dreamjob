"""Le scoring : code pur, donc entièrement testable.

Invariants défendus ici :
  - déterministe et rejouable ;
  - aucun appel réseau, jamais ;
  - c'est la pertinence (le métier, le contenu) qui fait le score ; le niveau,
    le diplôme et la langue ne font que retirer, les conditions que moduler ;
  - un point rédhibitoire ferme la porte, quoi qu'il arrive ailleurs.

Plusieurs tests rejouent en miniature une erreur mesurée sur les vraies offres
du propriétaire — le premier classement mettait des postes de responsable
administratif et financier devant des postes d'analyste crédit.
"""

import pytest

from app.config import PoidsScoring
from app.models import Offer, Profile
from app.scoring.cible import construire
from app.scoring.corpus import NEUTRE, Corpus
from app.scoring.explain import expliquer
from app.scoring.extraction import extraire
from app.scoring.score import (
    LOC_MEME_PAYS,
    LOC_MEME_VILLE,
    LOC_PAYS_ACCEPTE,
    PLAFOND_REDHIBITOIRE,
    calculer,
    etalonner,
    score_contrat,
    score_langue,
    score_pays,
)

POIDS = PoidsScoring()

DESCRIPTION_RISQUES = (
    "Au sein de la direction des risques, vous évaluez la solvabilité des "
    "contreparties, suivez les encours et produisez l'analyse financière des "
    "dossiers de crédit. Maîtrise d'Excel indispensable."
)
DESCRIPTION_COMPTA = (
    "Vous tenez la comptabilité générale et auxiliaire, assurez le lettrage des "
    "comptes fournisseurs, préparez les déclarations fiscales, la paie et le "
    "bilan annuel avec l'expert-comptable."
)


def profil(**kw) -> Profile:
    base = dict(
        titre_vise="Analyste risques de crédit",
        annees_experience=3,
        ville="Paris", pays="France",
        skills=[{"nom": "Risque de crédit", "ancree": True},
                {"nom": "Analyse financière", "ancree": True},
                {"nom": "Excel", "ancree": False}],
        secteurs=["Banque et assurance"],
        experiences=[{"poste": "Chargé d'affaires entreprises", "entreprise": "Banque X",
                      "debut": "2023", "fin": "2025",
                      "description": "Suivi d'un portefeuille de vingt entreprises : "
                                     "analyse de la solvabilité, des encours et des garanties.",
                      "tags": ["Crédit", "Risque"]}],
        formations=[{"diplome": "Master 2 Finance", "etablissement": "EM", "annee": "2023"}],
        langues=[{"code": "fr", "niveau": "natif"}, {"code": "en", "niveau": "intermédiaire"}],
        pays_acceptes=["France", "Luxembourg"],
        contrats_acceptes=["CDI", "CDD", "Stage"],
    )
    return Profile(**{**base, **kw})


def offre(**kw) -> Offer:
    base = dict(
        source="test", source_id="1",
        titre="Analyste risques de crédit (H/F)",
        entreprise="Banque Exemple", lieu="75 - Paris", pays="France",
        type_contrat="CDI",
        description_brute=DESCRIPTION_RISQUES,
    )
    return Offer(**{**base, **kw})


def scorer(p=None, o=None, recherches=None, poids=POIDS, corpus=NEUTRE):
    p, o = p or profil(), o or offre()
    return calculer(p, o, extraire(o), poids, construire(p, recherches or []), corpus)


# --- Déterminisme ----------------------------------------------------------------


def test_deux_calculs_identiques_donnent_le_meme_score():
    assert scorer().score == scorer().score


def test_changer_les_poids_change_le_score_sans_rien_reextraire():
    p, o = profil(), offre(pays="Luxembourg", type_contrat="CDD")
    signaux, cible = extraire(o), construire(profil(), [])
    a = calculer(p, o, signaux, PoidsScoring(), cible).score
    b = calculer(p, o, signaux, PoidsScoring(part_conditions=0.8), cible).score
    assert a != b


# --- La pertinence : le métier et le contenu -------------------------------------------


def test_le_metier_vise_l_emporte_sur_un_mot_commun():
    """Le défaut d'origine : « financier » suffisait à rapprocher un poste de
    RAF d'un CV de risques, et le premier classement le mettait devant."""
    raf = scorer(o=offre(titre="Responsable administratif et financier",
                         description_brute=DESCRIPTION_COMPTA),
                 recherches=[["finance"]])
    analyste = scorer(o=offre(), recherches=[["finance"]])
    assert analyste.detail["metier"] > raf.detail["metier"] + 30
    assert analyste.score > raf.score + 30


def test_un_diplome_n_est_pas_un_metier():
    """Le « Master » d'un Master 2 rapprochait le CV d'un poste de Scrum Master."""
    o = offre(titre="Scrum Master", description_brute="Animation des rituels agiles.")
    assert scorer(o=o).detail["metier"] == 0.0


def test_reprendre_un_intitule_vise_ne_suffit_pas_si_le_reste_parle_d_un_autre_metier():
    """« Ingénieur analyses de risques cybersécurité » reprend « analyste
    risques » — et parle d'un tout autre métier."""
    recherches = [["analyste risques"]]
    cyber = scorer(o=offre(titre="Ingénieur analyse de risques cybersécurité"),
                   recherches=recherches)
    risques = scorer(o=offre(titre="Analyste risques opérationnels"), recherches=recherches)
    assert risques.detail["metier"] > cyber.detail["metier"] + 20


def test_une_association_nouvelle_n_est_pas_un_mot_inconnu():
    """« Trading Risk and Control » était pénalisé parce que le CV ne disait
    pas « risk trading », alors qu'il connaissait chacun des mots."""
    p = profil(skills=[{"nom": "Trading", "ancree": True}, {"nom": "Risque", "ancree": True},
                       {"nom": "Contrôle", "ancree": True}])
    resultat = scorer(p=p, o=offre(titre="Trading Risk and Control"))
    assert resultat.metier_precision == pytest.approx(1.0)


def test_les_mots_cles_d_une_experience_disent_un_metier():
    """Aucune recherche ne disait « crédit » : sans les mots-clés de ses
    expériences, un CV de risque de crédit ne reconnaissait pas « Analyste
    crédit »."""
    o = offre(titre="Analyste crédit")
    sans_theme = profil(titre_vise="Trésorier", experiences=[
        {"poste": "Stagiaire", "description": "Suivi des créances.", "tags": []}])
    avec_theme = profil(titre_vise="Trésorier", experiences=[
        {"poste": "Stagiaire", "description": "Suivi des créances.", "tags": ["Crédit"]}])
    assert scorer(p=avec_theme, o=o).metier_rappel > scorer(p=sans_theme, o=o).metier_rappel


def test_le_contenu_se_lit_face_aux_meilleures_offres_du_compte():
    """Un CV court produit des similarités minuscules : étalonnées sur les
    offres du compte, la meilleure vaut 100."""
    p = profil()
    offres = [offre(source_id=str(i), titre=t, description_brute=d) for i, (t, d) in enumerate([
        ("Analyste risques de crédit", DESCRIPTION_RISQUES),
        ("Comptable", DESCRIPTION_COMPTA),
        ("Boulanger", "Vous confectionnez les pains et viennoiseries chaque matin."),
    ])]
    signaux = [extraire(o) for o in offres]
    corpus = Corpus.depuis(signaux)
    cible = construire(p, [])
    etalonner(cible, signaux, corpus)
    notes = [calculer(p, o, s, POIDS, cible, corpus).detail["competences"]
             for o, s in zip(offres, signaux)]
    assert notes[0] == 100.0
    assert notes[0] > max(notes[1], notes[2])


def test_un_profil_totalement_vide_donne_zero_sans_planter():
    resultat = scorer(p=Profile())
    assert resultat.score == 0.0
    assert {"metier", "competences"} <= set(resultat.non_evaluables)


# --- L'accessibilité ne fait que retirer --------------------------------------------------


def test_etre_au_bon_niveau_ne_rend_pas_un_poste_pertinent():
    """Quand niveau, diplôme et langue s'additionnaient au reste, un poste
    sans rapport mais « compatible » empochait d'office le tiers du score."""
    boulanger = scorer(o=offre(titre="Boulanger", description_brute=(
        "Vous confectionnez les pains et les viennoiseries de la boutique chaque "
        "matin, dans le respect des règles d'hygiène.")))
    assert boulanger.detail.get("seniorite") == 100.0
    assert boulanger.score < 20


def test_un_poste_de_direction_est_hors_de_portee():
    resultat = scorer(o=offre(titre="Directeur administratif et financier"))
    assert resultat.detail["seniorite"] <= 5
    assert resultat.score <= PLAFOND_REDHIBITOIRE
    assert any("expérience" in r for r in resultat.redhibitoires)


def test_des_annees_chiffrees_trop_loin_du_profil_ferment_la_porte():
    o = offre(description_brute=DESCRIPTION_RISQUES + " Au moins 10 ans d'expérience exigés.")
    assert scorer(o=o).score <= PLAFOND_REDHIBITOIRE


def test_un_stage_accepte_n_est_pas_un_poste_trop_junior():
    o = offre(titre="Stage analyste risques de crédit")
    assert scorer(o=o).detail["seniorite"] == 90.0
    sans_stage = profil(contrats_acceptes=["CDI"])
    assert scorer(p=sans_stage, o=o).detail["seniorite"] == 70.0


def test_une_certification_exigee_que_le_candidat_n_a_pas_ferme_la_porte():
    o = offre(description_brute=DESCRIPTION_RISQUES + " Diplôme d'expertise comptable exigé.")
    resultat = scorer(o=o)
    assert resultat.score <= PLAFOND_REDHIBITOIRE
    assert any("expert-comptable" in r for r in resultat.redhibitoires)


def test_un_poste_reserve_aux_fonctionnaires_ferme_la_porte():
    o = offre(description_brute=DESCRIPTION_RISQUES + " Recrutement par voie statutaire.")
    assert scorer(o=o).score <= PLAFOND_REDHIBITOIRE


def test_un_poste_ouvert_aux_contractuels_reste_ouvert():
    o = offre(description_brute=DESCRIPTION_RISQUES
              + " Poste ouvert aux fonctionnaires et aux contractuels.")
    assert scorer(o=o).score > PLAFOND_REDHIBITOIRE


def test_un_poste_a_bac_plus_2_pour_un_bac_plus_5():
    o = offre(description_brute=DESCRIPTION_RISQUES + " Titulaire d'un BTS ou d'un DUT.")
    assert scorer(o=o).detail["formation"] == 55.0


def test_une_langue_que_le_candidat_ne_parle_pas_ferme_la_porte():
    o = offre(description_brute=(
        "Sie analysieren die Kreditrisiken unserer Firmenkunden und erstellen die "
        "Berichte für die Geschäftsleitung. Wir erwarten sehr gute Kenntnisse und "
        "eine selbstständige Arbeitsweise in einem internationalen Team."))
    resultat = scorer(o=o)
    assert resultat.detail["langue"] == 0.0
    assert resultat.score <= PLAFOND_REDHIBITOIRE


# --- Les conditions modulent -------------------------------------------------------------


def test_les_conditions_modulent_sans_faire_le_score():
    ici = scorer(o=offre())
    ailleurs = scorer(o=offre(lieu="Luxembourg", pays="Luxembourg", type_contrat="CDD"))
    assert ailleurs.score < ici.score
    # … mais au plus de `part_conditions` : le poste reste un bon poste.
    assert ailleurs.score >= ici.score * (1 - POIDS.part_conditions)


def test_un_pays_refuse_ferme_la_porte():
    assert scorer(o=offre(pays="Brésil", lieu="São Paulo")).score <= PLAFOND_REDHIBITOIRE


def test_un_contrat_non_souhaite_ferme_la_porte():
    assert scorer(o=offre(type_contrat="Alternance")).score <= PLAFOND_REDHIBITOIRE


def test_le_lieu_compte_quatre_paliers():
    p = profil(pays_acceptes=["France", "Luxembourg"])
    assert score_pays(p, offre(lieu="75 - Paris")) == LOC_MEME_VILLE
    assert score_pays(p, offre(lieu="69 - Lyon")) == LOC_MEME_PAYS
    assert score_pays(p, offre(lieu="Luxembourg", pays="Luxembourg")) == LOC_PAYS_ACCEPTE
    assert score_pays(p, offre(pays="Brésil")) == 0.0


def test_sans_pays_de_residence_aucune_offre_n_est_penalisee():
    p = profil(pays="", ville="")
    assert score_pays(p, offre(lieu="Luxembourg", pays="Luxembourg")) == LOC_MEME_PAYS


def test_l_ordre_des_contrats_porte_la_preference():
    p = profil(contrats_acceptes=["CDI", "CDD", "Stage"])
    assert score_contrat(p, offre(type_contrat="CDI")) == 100.0
    assert score_contrat(p, offre(type_contrat="CDD")) == 80.0
    assert score_contrat(p, offre(type_contrat="Stage")) == 60.0


def test_langue_selon_le_niveau_declare():
    o = offre(description_brute=(
        "You will monitor the credit risk exposures of our corporate clients and "
        "report to the head of risk every week with clear recommendations."))
    assert score_langue(profil(), extraire(o)) == 70.0


def test_une_offre_trop_courte_ne_perd_pas_de_points_sur_la_langue():
    resultat = scorer(o=offre(description_brute="Poste en CDI."))
    assert "langue" in resultat.non_evaluables


# --- L'explication ---------------------------------------------------------------------------


def _expliquer(p=None, o=None, recherches=None):
    p, o = p or profil(), o or offre()
    signaux = extraire(o)
    resultat = calculer(p, o, signaux, POIDS, construire(p, recherches or []))
    return expliquer(resultat, p, o, signaux)


def test_l_explication_dit_quel_metier_l_offre_rejoint_et_d_ou_il_vient():
    texte = _expliquer(recherches=[["analyste risques"]])
    assert "Métier : rejoint" in texte
    assert "En commun avec votre CV" in texte


def test_l_explication_parle_avec_les_mots_de_l_annonce():
    """Des racines (« solvabilit ») ne se lisent pas : on reprend le mot écrit."""
    assert "solvabilité" in _expliquer()


def test_un_point_redhibitoire_ouvre_l_explication():
    texte = _expliquer(o=offre(titre="Directeur administratif et financier"))
    assert texte.splitlines()[0].startswith("Rédhibitoire")


def test_l_explication_ne_cite_ni_l_employeur_ni_la_ville():
    texte = _expliquer(o=offre(entreprise="Globex", description_brute=(
        DESCRIPTION_RISQUES + " Globex recrute à Paris pour son siège.")))
    assert "globex" not in texte.lower().split("conditions")[0]


def test_un_critere_non_evaluable_reste_muet_dans_l_explication():
    texte = _expliquer(p=profil(annees_experience=0))
    assert "Niveau" not in texte


def test_l_explication_des_conditions_reste_lisible_dans_excel():
    texte = _expliquer(p=profil(contrats_acceptes=["CDD", "CDI"]))
    assert "2e choix" in texte
    texte.encode("cp1252")      # lève UnicodeEncodeError si un caractère passe mal


# --- Le scoring n'appelle jamais le LLM ------------------------------------------------------


def test_aucun_appel_reseau_pendant_un_scoring(monkeypatch):
    """Garde-fou : si quelqu'un réintroduit un appel LLM ici, ce test casse."""
    import httpx

    def interdit(*_, **__):
        raise AssertionError("le scoring a tenté un appel réseau")

    monkeypatch.setattr(httpx.Client, "request", interdit)
    monkeypatch.setattr(httpx.Client, "send", interdit)
    assert scorer().score > 0
