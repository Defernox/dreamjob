"""L'empreinte d'une annonce : stable malgré la mise en forme, discriminante sur le fond.

C'est ce qui permet de reconnaître la même offre republiée par un autre site.
"""

from app.services.dedup import calculer_hash, normaliser


def _h(titre="Analyste risques", entreprise="Banque Exemple",
       lieu="75 - Paris 09", description="Vous évaluez la solvabilité."):
    return calculer_hash(titre, entreprise, lieu, description)


def test_normalisation_neutralise_casse_accents_et_ponctuation():
    assert normaliser("  Chargé(e) de COM' digitale ! ") == "charge e de com digitale"
    assert normaliser(None) == ""


def test_meme_annonce_mise_en_forme_differemment():
    assert _h() == _h(titre="ANALYSTE   RISQUES", entreprise="Banque  Exemple",
                      lieu="75 – PARIS 09")


def test_poste_different_chez_le_meme_employeur():
    assert _h() != _h(titre="Analyste crédit")


def test_meme_poste_dans_deux_villes():
    assert _h() != _h(lieu="69 - Lyon 03")


def test_seul_le_debut_de_la_description_compte():
    """Les sites ajoutent leurs mentions légales à la fin : elles ne doivent pas
    empêcher de reconnaître un doublon."""
    debut = "a" * 500
    assert _h(description=debut + " mentions legales du site A") == \
           _h(description=debut + " conditions generales du site B")


def test_deux_descriptions_differentes_des_le_debut():
    assert _h(description="Poste en salle de marché") != \
           _h(description="Poste en back office")
