"""Non-régression : les défauts trouvés aux revues du module scoring.

Chaque test nomme le comportement fautif d'origine, pour qu'on sache ce qu'on
casse si on le rétablit par inadvertance.
"""

import pytest

from app.scoring.cible import construire
from app.scoring.explain import expliquer
from app.scoring.extraction import VERSION as VERSION_SIGNAUX
from app.scoring.extraction import extraire
from app.scoring.score import NIVEAU_LANGUE_PAR_DEFAUT, _niveau_du_profil, calculer
from app.scoring.synonymes import equivalents
from app.scoring.texte import LONGUEUR_CACHABLE, _normaliser_cache, normaliser

from .test_scoring import POIDS, offre, profil, scorer

# --- Les niveaux de langue -----------------------------------------------------


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


# --- La version des signaux ------------------------------------------------------


def test_une_version_de_signaux_perimee_force_un_rescoring(session):
    """Incrémenter extraction.VERSION ne servait à rien : l'offre n'était pas
    revisitée et gardait ses signaux d'avant."""
    from app.config import reglages
    from app.models import ScoreOffre
    from app.models.base import maintenant
    from app.services.acces import proprietaire
    from app.services.scoring import scorer_toutes

    moi = proprietaire(session).id
    p = profil()
    p.utilisateur_id = moi
    session.add(p)
    o = offre()
    o.extraction = {"version": VERSION_SIGNAUX - 1, "langue": "fr",
                    "exigences_langues": [], "texte_secteur": "", "vocabulaire": []}
    session.add(o)
    session.flush()
    # Une note à jour en tout, sauf la version des signaux qui l'a produite.
    session.add(ScoreOffre(utilisateur_id=moi, offer_id=o.id, score=42.0,
                           poids_version=reglages().scoring.version,
                           version_signaux=VERSION_SIGNAUX - 1, scored_at=maintenant()))
    session.commit()

    assert scorer_toutes(session, moi)["scorees"] == 1
    session.refresh(o)
    assert o.extraction["version"] == VERSION_SIGNAUX


def test_une_offre_a_jour_n_est_pas_rescoree_pour_rien(session):
    from app.services.acces import proprietaire
    from app.services.scoring import scorer_toutes

    from .conftest import ajouter_offre

    moi = proprietaire(session).id
    p = profil()
    p.utilisateur_id = moi
    session.add(p)
    o = offre()
    ajouter_offre(session, moi, **{k: v for k, v in o.model_dump().items() if v is not None})
    session.commit()
    scorer_toutes(session, moi)
    assert scorer_toutes(session, moi)["scorees"] == 0


# --- L'explication nomme la bonne langue -------------------------------------------


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
    texte = expliquer(calculer(p, o, signaux, POIDS, construire(p, [])), p, o, signaux)
    assert "EN exigé" in texte
    assert "FR, non" not in texte


def test_une_description_vide_laisse_la_langue_non_evaluee():
    """Mieux vaut ne rien affirmer qu'un repli sur un intitulé trop court."""
    signaux = extraire(offre(description_brute=""))
    assert signaux.langue == ""
    assert "langue" in scorer(o=offre(description_brute="")).non_evaluables


# --- Le cache de normalisation --------------------------------------------------------


def test_une_description_entiere_n_entre_pas_dans_le_cache():
    """Le cache retenait la clé ET la valeur — le texte en double — pour des
    descriptions uniques par offre, donc pour un taux de succès nul."""
    _normaliser_cache.cache_clear()
    normaliser("x" * (LONGUEUR_CACHABLE + 1))
    assert _normaliser_cache.cache_info().currsize == 0
    normaliser("Analyse financière")
    assert _normaliser_cache.cache_info().currsize == 1


# --- L'index des synonymes ---------------------------------------------------------------


def test_l_index_des_synonymes_est_symetrique():
    """Un mot présent dans deux familles héritait de l'union, pas ses voisins :
    le score dépendait alors du terme choisi dans le profil."""
    from app.scoring.synonymes import _index_inverse

    index = _index_inverse([{"capital", "actif"}, {"capital", "fonds"}])
    assert index["actif"] == index["fonds"] == index["capital"]


def test_les_familles_existantes_restent_symetriques():
    for mot in ("risque", "credit", "treasury", "banking", "comptable", "trading"):
        for voisin in equivalents(mot):
            assert mot in equivalents(voisin), f"{mot} <-> {voisin}"


def test_negociation_commerciale_et_trading_ne_sont_plus_synonymes():
    """Un CV qui « négocie des partenariats » devenait un CV de trader."""
    assert "trading" not in equivalents("negociation")


def test_un_manager_n_est_pas_une_activite_de_gestion():
    """« Finance Manager » devenait un poste « de gestion »."""
    assert "gestion" not in equivalents("manager")
    assert "responsable" in equivalents("manager")
