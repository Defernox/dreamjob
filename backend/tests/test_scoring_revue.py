"""Non-régression : les onze défauts trouvés à la revue du module scoring.

Chaque test nomme le comportement fautif d'origine, pour qu'on sache ce qu'on
casse si on le rétablit par inadvertance.
"""

import pytest

from app.models import Offer, Profile
from app.scoring.explain import expliquer
from app.scoring.extraction import VERSION as VERSION_SIGNAUX
from app.scoring.extraction import Signaux, extraire
from app.scoring.score import (
    CREDIT_SECTEUR_FAIBLE,
    NIVEAU_LANGUE_PAR_DEFAUT,
    Resultat,
    _niveau_du_profil,
    calculer,
    score_competences,
    score_secteur,
)
from app.scoring.synonymes import equivalents
from app.scoring.texte import LONGUEUR_CACHABLE, _normaliser_cache, normaliser

from .test_scoring import POIDS, offre, profil, scorer


def _signaux(texte_secteur="", vocabulaire="", **kw):
    from app.scoring.texte import mots
    return Signaux(texte_secteur=texte_secteur,
                   vocabulaire=sorted(set(mots(vocabulaire))), **kw)


# --- 1. Le secteur connaît les synonymes ------------------------------------


def test_le_secteur_reconnait_un_intitule_anglais():
    """Il comparait par simple appartenance d'ensemble : « Finance » ne
    rencontrait jamais « financial markets », et un quart des offres de la base
    en ressortait sous-notée."""
    p = profil(secteurs=["finance"])
    sig = _signaux(texte_secteur="banking analyst",
                   vocabulaire="Banking Analyst, financial markets, credit risk")
    assert score_secteur(p, sig, Resultat(score=0)) > 0


def test_le_secteur_pondere_les_mots_generiques():
    """« gestion de patrimoine » reconnu sur le seul mot « gestion » ne doit pas
    valoir la moitié du critère : « gestion » est générique, pas signant."""
    p = profil(secteurs=["gestion de patrimoine"])
    generique = _signaux(texte_secteur="gestion des stocks")
    complet = _signaux(texte_secteur="gestion de patrimoine")
    note_generique = score_secteur(p, generique, Resultat(score=0))
    note_complete = score_secteur(p, complet, Resultat(score=0))
    assert note_generique < 40.0 < note_complete


# --- 2. Les niveaux de langue -----------------------------------------------


@pytest.mark.parametrize("saisie, attendu", [
    ("Notion", 40.0),           # le singulier manquait : il valait 85
    ("notions", 40.0),
    ("Bases", 40.0),
    ("natif", 100.0),
    ("intermédiaire", 70.0),
])
def test_un_niveau_ecrit_a_la_main_est_reconnu(saisie, attendu):
    p = profil(langues=[{"code": "de", "niveau": saisie}])
    assert _niveau_du_profil(p, "de") == attendu


def test_deux_niveaux_dans_la_meme_saisie_retiennent_le_plus_prudent():
    """« courant (B2) » vaut B2. Retenir le premier jeton rencontré faisait
    dépendre la note de l'ordre de frappe."""
    p = profil(langues=[{"code": "en", "niveau": "courant (B2)"}])
    assert _niveau_du_profil(p, "en") == 70.0


def test_un_niveau_illisible_ne_vaut_pas_une_quasi_maitrise():
    """« TOEIC 775 » ne doit pas être lu comme presque bilingue."""
    p = profil(langues=[{"code": "en", "niveau": "TOEIC 775"}])
    assert _niveau_du_profil(p, "en") == NIVEAU_LANGUE_PAR_DEFAUT
    assert NIVEAU_LANGUE_PAR_DEFAUT <= 70.0


# --- 3. Titre partiel contre corps complet ----------------------------------


def test_un_titre_a_moitie_reconnu_n_ecrase_pas_le_corps():
    """Le repli ne se déclenchait que si le titre donnait exactement zéro : un
    titre à moitié pertinent faisait donc BAISSER le score."""
    p = profil(secteurs=["banque de financement et investissement"])
    corps = "banque de financement et investissement structuré"
    partiel = _signaux(texte_secteur="analyste banque", vocabulaire=corps)
    muet = _signaux(texte_secteur="analyste credit", vocabulaire=corps)

    note_partielle = score_secteur(p, partiel, Resultat(score=0))
    note_muette = score_secteur(p, muet, Resultat(score=0))
    assert note_partielle >= note_muette


# --- 4. Le bruit sous le seuil ----------------------------------------------


def test_des_competences_frolant_un_mot_generique_ne_saturent_pas_le_score():
    """Dix compétences en « gestion de … » face à une offre de boulangerie
    additionnaient leurs miettes jusqu'à 83/100, sans qu'aucune ne soit
    rapportée à l'utilisateur."""
    p = profil(skills=[{"nom": f"gestion des {quoi}", "ancree": False} for quoi in
                       ("risques de crédit", "portefeuilles obligataires", "encours",
                        "créances", "contreparties", "budgets", "bilans",
                        "prévisions", "trésoreries", "actifs")])
    sig = _signaux(vocabulaire="gestion quotidienne de l'équipe commerciale "
                               "en boulangerie industrielle")
    resultat = Resultat(score=0)
    note = score_competences(p, sig, resultat)
    assert note < 40.0
    # Le score et l'explication doivent dire la même chose.
    assert resultat.autres_trouvees == []


def test_le_score_et_l_explication_ne_se_contredisent_pas():
    p = profil(skills=[{"nom": "gestion des risques de crédit", "ancree": False}])
    sig = _signaux(vocabulaire="gestion des plannings d'équipe")
    resultat = Resultat(score=0)
    note = score_competences(p, sig, resultat)
    assert (note > 0) == bool(resultat.autres_trouvees)


# --- 5. La version des signaux ----------------------------------------------


def test_une_version_de_signaux_perimee_force_un_rescoring(session):
    """Incrémenter extraction.VERSION ne servait à rien : l'offre n'était pas
    revisitée et gardait ses signaux d'avant."""
    from app.services.scoring import scorer_toutes

    session.add(profil())
    o = offre()
    o.score, o.poids_version = 42.0, 1
    o.extraction = {"version": VERSION_SIGNAUX - 1, "langue": "fr",
                    "exigences_langues": [], "texte_secteur": "", "vocabulaire": []}
    session.add(o)
    session.commit()

    assert scorer_toutes(session)["scorees"] == 1
    session.refresh(o)
    assert o.extraction["version"] == VERSION_SIGNAUX


def test_une_offre_a_jour_n_est_pas_rescoree_pour_rien(session):
    from app.services.scoring import scorer_toutes

    session.add(profil())
    session.add(offre())
    session.commit()
    scorer_toutes(session)
    assert scorer_toutes(session)["scorees"] == 0


# --- 6. L'explication nomme la bonne langue ---------------------------------


def test_l_explication_nomme_la_langue_exigee_et_non_celle_de_redaction():
    """Une offre en français réclamant un anglais courant annonçait
    « langue FR non maîtrisée » à un francophone natif."""
    p = profil(langues=[{"code": "fr", "niveau": "natif"}])
    o = offre(description_brute=(
        "Au sein de la direction des risques, vous suivez les encours et les "
        "contreparties de la banque. Un anglais courant est exigé pour ce poste, "
        "les échanges avec les équipes de Londres étant quotidiens."
    ))
    signaux = extraire(o)
    assert "en" in signaux.exigences_langues
    texte = expliquer(calculer(p, o, signaux, POIDS), p, o, signaux)
    assert "EN exigé" in texte
    assert "FR non maîtrisée" not in texte


# --- 7. Le repli de détection de langue -------------------------------------


def test_une_description_vide_laisse_la_langue_non_evaluee():
    """Le repli sur le titre ne se déclenchait jamais (un intitulé compte 6 à 10
    jetons, le seuil en exige 12) : mieux vaut ne rien affirmer."""
    signaux = extraire(offre(description_brute=""))
    assert signaux.langue == ""
    resultat = scorer(o=offre(description_brute=""))
    assert "langue" in resultat.non_evaluables


# --- 8. Non évaluable n'est pas zéro ----------------------------------------


def test_un_critere_non_evaluable_ne_sauve_pas_une_offre_hors_cible():
    """Entorse assumée à « non évaluable ⇒ pas de pénalité » : un critère qu'on
    ne peut pas juger n'est pas une preuve de pertinence. Un profil sans
    compétences dont le secteur ne correspond pas reste plafonné."""
    p = profil(skills=[], secteurs=["boulangerie artisanale"])
    resultat = scorer(p=p, plafond=25.0)
    assert "competences" in resultat.non_evaluables
    assert resultat.hors_cible
    assert resultat.score <= 25.0


def test_le_plafond_s_applique_toujours_quand_le_critere_est_evalue_a_zero():
    p = profil(skills=[{"nom": "soudure à l'arc", "ancree": True}],
               secteurs=["métallurgie"])
    resultat = scorer(p=p, plafond=25.0)
    assert resultat.hors_cible
    assert resultat.score <= 25.0


# --- 9. Le cache de normalisation -------------------------------------------


def test_une_description_entiere_n_entre_pas_dans_le_cache():
    """Le cache retenait la clé ET la valeur — le texte en double — pour des
    descriptions uniques par offre, donc pour un taux de succès nul."""
    _normaliser_cache.cache_clear()
    normaliser("x" * (LONGUEUR_CACHABLE + 1))
    assert _normaliser_cache.cache_info().currsize == 0
    normaliser("Analyse financière")
    assert _normaliser_cache.cache_info().currsize == 1


# --- 10. L'index des synonymes ----------------------------------------------


def test_l_index_des_synonymes_est_symetrique():
    """Un mot présent dans deux familles héritait de l'union, pas ses voisins :
    le score dépendait alors du terme choisi dans le profil."""
    from app.scoring.synonymes import _index_inverse

    index = _index_inverse([{"capital", "actif"}, {"capital", "fonds"}])
    assert index["actif"] == index["fonds"] == index["capital"]


def test_les_familles_existantes_restent_symetriques():
    for mot in ("risque", "credit", "treasury", "banking"):
        for voisin in equivalents(mot):
            assert mot in equivalents(voisin), f"{mot} <-> {voisin}"


# --- 11. Le vocabulaire n'est construit qu'une fois --------------------------


def test_le_vocabulaire_n_est_pas_reconstruit_par_chaque_critere():
    """Les deux critères le reconstruisaient chacun de leur côté."""
    p, o = profil(), offre()
    signaux = extraire(o)
    vus = []

    class Espion(list):
        def __iter__(self):
            vus.append(1)
            return super().__iter__()

    signaux.vocabulaire = Espion(signaux.vocabulaire)
    calculer(p, o, signaux, POIDS)
    assert len(vus) == 1
