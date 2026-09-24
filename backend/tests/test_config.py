"""Le réglage des poids doit rester sain quoi qu'on écrive dans config.yaml."""

from app.config import PoidsScoring, reglages

GROUPES = (PoidsScoring.PERTINENCE, PoidsScoring.ACCESSIBILITE, PoidsScoring.CONDITIONS)


def test_chaque_groupe_est_normalise_a_part():
    """Trois groupes, trois questions : seuls les rapports internes comptent."""
    normalises = reglages().scoring.poids.normalises()
    for groupe in GROUPES:
        assert abs(sum(normalises[c] for c in groupe) - 1.0) < 1e-9


def test_tous_les_criteres_ont_un_poids():
    """Un critère sans poids se calculerait sans jamais compter."""
    poids = reglages().scoring.poids.en_dict()
    assert set(poids) == {c for groupe in GROUPES for c in groupe}


def test_poids_non_standards_restent_normalises():
    # L'utilisateur écrit ce qu'il veut : 6/4 ou 60/40, c'est pareil.
    poids = PoidsScoring(metier=6, competences=4)
    normalises = poids.normalises()
    assert normalises["metier"] == 0.6
    assert normalises["competences"] == 0.4


def test_poids_tous_a_zero_ne_divise_pas_par_zero():
    zeros = {c: 0 for groupe in GROUPES for c in groupe}
    assert sum(PoidsScoring(**zeros).normalises().values()) == 0.0


def test_les_parts_restent_des_proportions():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PoidsScoring(part_conditions=1.5)
