"""Le réglage des poids doit rester sain quoi qu'on écrive dans config.yaml."""

from app.config import PoidsScoring, reglages


def test_poids_par_defaut_font_100():
    assert reglages().scoring.poids.total == 100


def test_normalisation_somme_a_1():
    normalises = reglages().scoring.poids.normalises()
    assert abs(sum(normalises.values()) - 1.0) < 1e-9


def test_poids_non_standards_restent_normalises():
    # L'utilisateur écrit ce qu'il veut : 60/20/10/5/5 = 100, ou 6/2/1/0/1 = 10.
    poids = PoidsScoring(competences=6, secteur=2, pays=1, langue=0, contrat=1)
    normalises = poids.normalises()
    assert abs(sum(normalises.values()) - 1.0) < 1e-9
    assert normalises["competences"] == 0.6
    assert normalises["langue"] == 0.0


def test_poids_tous_a_zero_ne_divise_pas_par_zero():
    poids = PoidsScoring(competences=0, secteur=0, pays=0, langue=0, contrat=0)
    assert sum(poids.normalises().values()) == 0.0
