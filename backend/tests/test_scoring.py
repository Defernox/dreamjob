"""Le scoring : code pur, donc entièrement testable.

Invariants défendus ici :
  - déterministe et rejouable ;
  - aucun appel réseau, jamais ;
  - un critère qu'on ne peut pas juger ne pénalise pas l'offre ;
  - une offre hors cible ne remonte pas grâce au contrat ou au pays.
"""

import pytest

from app.config import PoidsScoring
from app.models import Offer, Profile
from app.scoring.explain import expliquer
from app.scoring.extraction import extraire
from app.scoring.score import calculer

POIDS = PoidsScoring()


def profil(**kw) -> Profile:
    base = dict(
        skills=[{"nom": "Gestion des risques de crédit", "ancree": True},
                {"nom": "Analyse financière", "ancree": True},
                {"nom": "Excel", "ancree": False},
                {"nom": "Power BI", "ancree": False}],
        secteurs=["banque et assurance", "finance de marché"],
        langues=[{"code": "fr", "niveau": "natif"}, {"code": "en", "niveau": "intermédiaire"}],
        pays_acceptes=["France", "Luxembourg"],
        contrats_acceptes=["CDI", "CDD", "Alternance"],
    )
    return Profile(**{**base, **kw})


def offre(**kw) -> Offer:
    base = dict(
        source="test", source_id="1",
        titre="Analyste risques de crédit (H/F)",
        entreprise="Banque Exemple", lieu="75 - Paris", pays="France",
        type_contrat="CDI",
        description_brute=(
            "Au sein de la direction des risques, vous évaluez la solvabilité des "
            "contreparties, suivez les encours et produisez l'analyse financière "
            "des dossiers. Maîtrise d'Excel indispensable."
        ),
        raw={"romeCode": "C1206", "romeLibelle": "Gestion de clientèle bancaire"},
    )
    return Offer(**{**base, **kw})


def scorer(p=None, o=None, poids=POIDS, plafond=100.0):
    p, o = p or profil(), o or offre()
    return calculer(p, o, extraire(o), poids, plafond)


# --- Déterminisme ----------------------------------------------------------


def test_deux_calculs_identiques_donnent_le_meme_score():
    assert scorer().score == scorer().score


def test_changer_les_poids_change_le_score_sans_rien_reextraire():
    """La promesse du projet : les poids se règlent sans rappeler quoi que ce soit."""
    o = offre()
    signaux = extraire(o)              # extraction faite UNE fois

    tout_competences = PoidsScoring(competences=100, secteur=0, pays=0, langue=0, contrat=0)
    tout_pays = PoidsScoring(competences=0, secteur=0, pays=100, langue=0, contrat=0)

    a = calculer(profil(), o, signaux, tout_competences)
    b = calculer(profil(), o, signaux, tout_pays)
    assert a.score != b.score
    assert b.score == 100.0            # pays accepté, et lui seul compte


# --- Compétences -----------------------------------------------------------


def test_une_competence_ancree_retrouvee_pese_lourd():
    trouvee = scorer().detail["competences"]
    absente = scorer(p=profil(skills=[{"nom": "Soudure TIG", "ancree": True}])).detail["competences"]
    assert trouvee > absente
    assert absente == 0.0


def test_les_mots_generiques_pesent_moins_que_les_mots_specifiques():
    """« gestion » est passe-partout ; « trésorerie » ne l'est pas."""
    specifique = scorer(p=profil(skills=[{"nom": "Gestion des encours", "ancree": True}]))
    generique = scorer(p=profil(skills=[{"nom": "Gestion des palettes", "ancree": True}]))
    assert specifique.detail["competences"] > generique.detail["competences"]


def test_une_competence_ancree_n_accepte_pas_l_a_peu_pres():
    """Une signature doit se retrouver telle quelle, pas « à peu près »."""
    ancree = scorer(p=profil(skills=[{"nom": "Solvabilitee", "ancree": True}]))
    ordinaire = scorer(p=profil(skills=[{"nom": "Solvabilitee", "ancree": False}]))
    assert ancree.detail["competences"] == 0.0
    assert ordinaire.detail["competences"] > 0.0


def test_un_profil_sans_competence_ne_bloque_pas_le_score():
    resultat = scorer(p=profil(skills=[]))
    assert "competences" in resultat.non_evaluables
    assert resultat.score > 0


def test_le_score_competences_n_est_pas_plafonne_par_la_taille_du_profil():
    """Ajouter des compétences non citées ne doit pas écraser le score : une
    annonce ne mentionne jamais tout un profil."""
    court = scorer(p=profil(skills=[{"nom": "Analyse financière", "ancree": True}]))
    long = scorer(p=profil(skills=[{"nom": "Analyse financière", "ancree": True}]
                                  + [{"nom": f"Compétence {i}", "ancree": False} for i in range(20)]))
    assert long.detail["competences"] >= court.detail["competences"] * 0.9


# --- Secteur ---------------------------------------------------------------


def test_un_secteur_reconnu_dans_l_intitule_vaut_mieux_que_dans_le_corps():
    dans_titre = scorer(p=profil(secteurs=["risques"]))
    dans_corps = scorer(p=profil(secteurs=["encours"]))
    assert dans_titre.detail["secteur"] > dans_corps.detail["secteur"] > 0


def test_secteur_hors_cible():
    assert scorer(p=profil(secteurs=["boulangerie"])).detail["secteur"] == 0.0


# --- Pays, langue, contrat -------------------------------------------------


def test_pays_binaire():
    assert scorer().detail["pays"] == 100.0
    assert scorer(o=offre(pays="Allemagne")).detail["pays"] == 0.0


def test_langue_selon_le_niveau_declare():
    assert scorer().detail["langue"] == 100.0        # français natif


def test_langue_non_maitrisee():
    p = profil(langues=[{"code": "de", "niveau": "notions"}])
    assert scorer(p=p).detail["langue"] == 0.0       # l'offre est en français


def test_l_ordre_des_contrats_porte_la_preference():
    p = profil(contrats_acceptes=["CDI", "CDD", "Alternance"])
    premier = calculer(p, offre(type_contrat="CDI"), extraire(offre()), POIDS)
    dernier = calculer(p, offre(type_contrat="Alternance"), extraire(offre()), POIDS)
    assert premier.detail["contrat"] == 100.0
    assert dernier.detail["contrat"] == 60.0         # accepté, mais en dernier


def test_un_contrat_accepte_ne_tombe_jamais_a_zero():
    p = profil(contrats_acceptes=["CDI", "CDD", "Stage", "Alternance", "V.I.E"])
    for contrat in p.contrats_acceptes:
        valeur = calculer(p, offre(type_contrat=contrat), extraire(offre()), POIDS).detail["contrat"]
        assert valeur >= 60.0


def test_contrat_non_souhaite():
    p = profil(contrats_acceptes=["CDI"])
    assert calculer(p, offre(type_contrat="Intérim"), extraire(offre()), POIDS).detail["contrat"] == 0.0


# --- Critères non évaluables -----------------------------------------------


def test_un_critere_non_evaluable_ne_penalise_pas_l_offre():
    """Un profil sans pays acceptés ne doit pas faire chuter toutes les offres."""
    complet = scorer()
    sans_pays = scorer(p=profil(pays_acceptes=[]))
    assert "pays" in sans_pays.non_evaluables
    assert "pays" not in sans_pays.detail
    # Le poids du pays est redistribué : le score reste du même ordre.
    assert abs(sans_pays.score - complet.score) < 15


def test_un_profil_totalement_vide_donne_zero_sans_planter():
    resultat = scorer(p=Profile())
    assert resultat.score == 0.0
    assert set(resultat.non_evaluables) == {"competences", "secteur", "pays", "langue", "contrat"}


def test_une_offre_trop_courte_ne_perd_pas_de_points_sur_la_langue():
    o = offre(description_brute="Poste à pourvoir.")
    resultat = calculer(profil(), o, extraire(o), POIDS)
    assert "langue" in resultat.non_evaluables


# --- Plafond hors cible ----------------------------------------------------


def test_une_offre_hors_cible_ne_remonte_pas_grace_au_contrat_et_au_pays():
    boulanger = offre(
        titre="Boulanger (H/F)",
        description_brute=("Vous confectionnez les pains et viennoiseries chaque matin "
                           "dans notre fournil artisanal, en respectant les recettes."),
        raw={"romeCode": "D1102", "romeLibelle": "Boulangerie - viennoiserie"},
    )
    sans_plafond = calculer(profil(), boulanger, extraire(boulanger), POIDS, 100.0)
    avec_plafond = calculer(profil(), boulanger, extraire(boulanger), POIDS, 25.0)

    assert sans_plafond.score >= 40.0, "sans plafond, pays+langue+contrat suffisent à 40 %"
    assert avec_plafond.score == 25.0
    assert avec_plafond.hors_cible is True


def test_le_plafond_ne_touche_pas_une_offre_pertinente():
    resultat = scorer(plafond=25.0)
    assert resultat.hors_cible is False
    assert resultat.score > 25.0


# --- Explication -----------------------------------------------------------


def _expliquer(p=None, o=None, plafond=100.0):
    p, o = p or profil(), o or offre()
    signaux = extraire(o)
    return expliquer(calculer(p, o, signaux, POIDS, plafond), p, o, signaux)


def test_l_explication_nomme_les_faits_qui_ont_compte():
    texte = _expliquer()
    assert "secteur banque et assurance" in texte
    assert "skills ancrées" in texte
    assert "pays OK" in texte
    assert "langue FR OK" in texte
    assert "CDI prioritaire" in texte


def test_l_explication_dit_pourquoi_une_offre_est_ecartee():
    texte = _expliquer(o=offre(pays="Allemagne", type_contrat="Intérim"))
    assert "pays hors liste (Allemagne)" in texte
    assert "Intérim non souhaité" in texte


def test_l_explication_signale_un_critere_non_evalue():
    assert "pays non évalué" in _expliquer(p=profil(pays_acceptes=[]))


def test_l_explication_d_une_offre_hors_cible_est_sans_ambiguite():
    boulanger = offre(titre="Boulanger (H/F)",
                      description_brute="Vous confectionnez les pains et viennoiseries "
                                        "chaque matin dans notre fournil artisanal.",
                      raw={"romeCode": "D1102"})
    assert "HORS CIBLE" in _expliquer(o=boulanger, plafond=25.0)


def test_l_explication_reste_en_ascii_imprimable():
    """Elle finit dans l'export Excel : pas de caractère exotique."""
    texte = _expliquer(p=profil(contrats_acceptes=["CDD", "CDI"]))
    assert "2e choix" in texte
    texte.encode("cp1252")      # lève UnicodeEncodeError si un caractère passe mal


# --- Le scoring n'appelle jamais le LLM ------------------------------------


def test_aucun_appel_reseau_pendant_un_scoring(monkeypatch):
    """Garde-fou : si quelqu'un réintroduit un appel LLM ici, ce test casse."""
    import httpx

    def interdit(*_, **__):
        raise AssertionError("le scoring a tenté un appel réseau")

    monkeypatch.setattr(httpx.Client, "request", interdit)
    monkeypatch.setattr(httpx.Client, "send", interdit)
    assert scorer().score > 0
