"""Le réglage des poids doit rester sain quoi qu'on écrive dans config.yaml."""

from app.config import PoidsScoring, reglages


def test_poids_par_defaut_font_100():
    assert reglages().scoring.poids.total == 100


def test_normalisation_somme_a_1():
    normalises = reglages().scoring.poids.normalises()
    assert abs(sum(normalises.values()) - 1.0) < 1e-9


# Les sept critères à zéro : chaque test part de là et n'active que ce qu'il
# mesure. Sans ce socle, ajouter un critère fausse silencieusement les
# proportions attendues — c'est ce qui est arrivé en ajoutant séniorité et
# fraîcheur.
AUCUN = dict(competences=0, secteur=0, pays=0, seniorite=0, langue=0,
             contrat=0, fraicheur=0)


def test_poids_non_standards_restent_normalises():
    # L'utilisateur écrit ce qu'il veut : 60/20/10/10 = 100, ou 6/2/1/1 = 10.
    poids = PoidsScoring(**{**AUCUN, "competences": 6, "secteur": 2,
                            "pays": 1, "contrat": 1})
    normalises = poids.normalises()
    assert abs(sum(normalises.values()) - 1.0) < 1e-9
    assert normalises["competences"] == 0.6
    assert normalises["langue"] == 0.0


def test_poids_tous_a_zero_ne_divise_pas_par_zero():
    assert sum(PoidsScoring(**AUCUN).normalises().values()) == 0.0
