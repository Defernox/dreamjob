"""Connecteur Adzuna — sans réseau."""

import pytest

from app.connectors.adzuna import PAYS, URL, AdzunaConnector
from app.connectors.base import ConnecteurNonConfigure, ErreurConnecteur, SearchQuery
from app.connectors.http import ErreurHttp, Reponse

from .test_france_travail import FauxHttp, FauxReglages

CONFIGURE = dict(ADZUNA_APP_ID="id", ADZUNA_APP_KEY="key")

OFFRE = {
    "id": "4321", "title": "Credit Risk Analyst",
    "company": {"display_name": "Global Bank"},
    "location": {"display_name": "London, UK"},
    "created": "2026-08-27T09:00:00Z",
    "contract_type": "permanent",
    "description": "You will assess the solvency of counterparties.",
    "redirect_url": "https://www.adzuna.co.uk/details/4321",
}


def _connecteur(reponses, **secrets):
    return AdzunaConnector(FauxHttp(reponses), FauxReglages(**(secrets or CONFIGURE)))


def _page(resultats):
    return Reponse(200, {"results": resultats, "count": len(resultats)}, "", {})


def test_sans_identifiants_le_connecteur_le_dit():
    c = AdzunaConnector(FauxHttp([]), FauxReglages())
    with pytest.raises(ConnecteurNonConfigure, match="developer.adzuna.com"):
        c.fetch(SearchQuery())


def test_conversion_d_une_offre():
    c = _connecteur([_page([OFFRE])])
    o = c.fetch(SearchQuery(pays=["Royaume-Uni"], max_offres=50))[0]
    assert o.source_id == "4321"
    assert o.entreprise == "Global Bank"
    assert o.pays == "Royaume-Uni"
    assert o.type_contrat == "CDI"
    assert o.url.endswith("/details/4321")


def test_un_pays_par_requete():
    """Adzuna n'expose qu'un pays à la fois : il faut une requête par pays."""
    c = _connecteur([_page([OFFRE])])
    c.fetch(SearchQuery(pays=["France", "Royaume-Uni", "Allemagne"], max_offres=150))
    codes = [a["url"] for a in c.http.appels]
    assert URL.format(pays="fr", page=1) in codes
    assert URL.format(pays="gb", page=1) in codes
    assert URL.format(pays="de", page=1) in codes


def test_les_pays_non_couverts_sont_ignores_sans_erreur():
    """Le Sénégal n'est pas chez Adzuna : ce n'est pas une panne."""
    c = _connecteur([_page([])])
    c.fetch(SearchQuery(pays=["France", "Sénégal", "Tunisie"], max_offres=50))
    assert len(c.http.appels) == 1      # seule la France a été interrogée


def test_aucun_pays_couvert_ne_leve_pas():
    c = _connecteur([])
    assert c.fetch(SearchQuery(pays=["Sénégal"], max_offres=50)) == []


def test_le_plafond_se_repartit_entre_les_pays():
    """Demander 150 offres ne doit pas en ramener 150 par pays."""
    c = _connecteur([_page([OFFRE])])
    c.fetch(SearchQuery(pays=["France", "Royaume-Uni"], max_offres=100))
    par_requete = c.http.appels[0]["params"]["results_per_page"]
    assert par_requete <= 50


@pytest.mark.parametrize("brute, attendu", [
    ({"contract_type": "permanent"}, "CDI"),
    ({"contract_type": "contract"}, "CDD"),
    ({"title": "Finance Internship"}, "Stage"),
    ({"title": "Data Engineer"}, ""),
    ({"contract_time": "part_time"}, "Autre"),
])
def test_traduction_des_contrats(brute, attendu):
    assert AdzunaConnector._contrat(brute) == attendu


def test_un_contrat_inconnu_ne_devient_pas_autre():
    """Adzuna omet souvent le type. « Autre » mettrait le critère à zéro pour une
    information qu'on n'a pas ; une chaîne vide le rend simplement non évaluable."""
    assert AdzunaConnector._contrat({"title": "Credit Risk Analyst"}) == ""


def test_identifiants_refuses_donnent_un_message_actionnable():
    c = _connecteur([ErreurHttp(401, "unauthorized")])
    with pytest.raises(ErreurConnecteur, match="ADZUNA_APP_ID"):
        c.fetch(SearchQuery(pays=["France"], max_offres=50))


def test_la_table_des_pays_ne_contient_que_des_pays_connus():
    """Une faute de frappe ici rendrait un pays silencieusement inatteignable."""
    from app.models.enums import PAYS_FILTRES

    assert set(PAYS) <= set(PAYS_FILTRES)
