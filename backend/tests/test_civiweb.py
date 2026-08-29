"""Connecteur Civiweb (V.I.E) — sans réseau."""

import pytest

from app.connectors.base import ErreurConnecteur, SearchQuery
from app.connectors.civiweb import URL_RECHERCHE, CiviwebConnector
from app.connectors.http import ErreurHttp, Reponse

from .test_france_travail import FauxHttp, FauxReglages

OFFRE = {
    "id": 245487, "missionTitle": "Junior Trader (H/F)",
    "organizationName": "BLUE CUBE (FRANCE)", "cityName": "LONDRES",
    "countryName": "ROYAUME-UNI", "missionType": "VIE",
    "creationDate": "2026-08-28T13:31:37Z",
    "missionDescription": "Vous rejoignez le desk de trading.",
    "missionProfile": "Profil recherché : bac+5 finance.",
}


def _connecteur(reponses):
    return CiviwebConnector(FauxHttp(reponses), FauxReglages())


def _page(resultats):
    return Reponse(200, {"result": resultats, "count": len(resultats)}, "", {})


def test_conversion_d_une_mission():
    c = _connecteur([_page([OFFRE])])
    o = c.fetch(SearchQuery(max_offres=10))[0]
    assert o.source == "civiweb"
    assert o.source_id == "245487"
    assert o.titre == "Junior Trader (H/F)"
    assert o.entreprise == "BLUE CUBE (FRANCE)"
    assert o.lieu == "LONDRES"
    assert o.pays == "Royaume-Uni"
    assert o.type_contrat == "V.I.E"
    assert o.url.endswith("/offres/245487")


def test_la_description_reunit_mission_et_profil():
    """Le scoring cherche les compétences dans les deux champs."""
    c = _connecteur([_page([OFFRE])])
    description = c.fetch(SearchQuery(max_offres=10))[0].description_brute
    assert "desk de trading" in description
    assert "bac+5 finance" in description


@pytest.mark.parametrize("brut, attendu", [
    ("ETATS-UNIS", "États-Unis"),
    ("ROYAUME-UNI", "Royaume-Uni"),
    ("ALLEMAGNE", "Allemagne"),
    ("SINGAPOUR", "Singapour"),
    ("IRLANDE", "Irlande"),
])
def test_les_pays_rejoignent_notre_vocabulaire(brut, attendu):
    """Sinon le critère pays du scoring ne reconnaîtrait jamais ces offres."""
    assert CiviwebConnector._pays({"countryName": brut}) == attendu


def test_un_pays_hors_de_notre_liste_n_est_pas_perdu():
    """Mieux vaut un libellé inconnu qu'une offre sans pays."""
    assert CiviwebConnector._pays({"countryName": "COREE DU SUD"}) != ""


def test_le_via_est_traite_comme_du_vie():
    c = _connecteur([_page([{**OFFRE, "missionType": "VIA"}])])
    assert c.fetch(SearchQuery(max_offres=10))[0].type_contrat == "V.I.E"


def test_pagination():
    lot = [{**OFFRE, "id": i} for i in range(50)]
    c = _connecteur([_page(lot), _page(lot[:10])])
    assert len(c.fetch(SearchQuery(max_offres=100))) == 60


def test_le_corps_est_envoye_en_json_pas_en_formulaire():
    """L'API rejette un formulaire : bug rencontré au premier branchement."""
    c = _connecteur([_page([])])
    c.fetch(SearchQuery(mots_cles=["finance"], max_offres=10))
    appel = c.http.appels[0]
    assert appel["corps_json"]["query"] == "finance"
    assert "donnees" not in appel


def test_une_cle_perimee_donne_un_message_actionnable():
    c = _connecteur([ErreurHttp(401, "unauthorized")])
    with pytest.raises(ErreurConnecteur, match="CIVIWEB_API_KEY"):
        c.fetch(SearchQuery(max_offres=10))
