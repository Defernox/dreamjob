"""Le scan de bout en bout, avec de fausses sources.

Ces tests couvrent deux critères d'acceptation du projet :
  - « Relancer un scan deux fois de suite ne crée aucun doublon. »
  - « Si un connecteur casse, les autres continuent. »
"""

import pytest
from sqlmodel import func, select

from app.connectors import registry
from app.connectors.base import (
    BaseConnector,
    ConnecteurNonConfigure,
    ErreurConnecteur,
    RawOffer,
    SearchQuery,
)
from app.models import Offer
from app.models.enums import StatutScan
from app.services.scan import lancer_scan


def _offre(source="test", identifiant="1", titre="Analyste risques",
           entreprise="Banque Exemple", lieu="Paris", pays="France",
           contrat="CDI", description="Vous évaluez la solvabilité."):
    return RawOffer(source=source, source_id=identifiant, titre=titre,
                    entreprise=entreprise, lieu=lieu, pays=pays,
                    type_contrat=contrat, description_brute=description)


def _source(cle, offres=None, erreur=None):
    """Fabrique une classe de connecteur qui rend `offres` ou lève `erreur`."""

    class FausseSource(BaseConnector):
        def fetch(self, query):
            if erreur is not None:
                raise erreur
            return list(offres or [])

    FausseSource.cle = cle
    FausseSource.libelle = cle
    return FausseSource


@pytest.fixture
def sources(monkeypatch):
    """Remplace l'inventaire réel des connecteurs le temps du test."""
    faux: dict = {}
    monkeypatch.setattr(registry, "CONNECTEURS", faux)
    return faux


def _compter_offres(session):
    return session.exec(select(func.count()).select_from(Offer)).one()


# --- Déduplication ---------------------------------------------------------


def test_relancer_le_meme_scan_ne_cree_aucun_doublon(session, sources):
    lot = [_offre(identifiant="1"), _offre(identifiant="2", titre="Analyste crédit")]
    sources["a"] = _source("a", lot)

    premier = lancer_scan(session, SearchQuery(), sources=["a"])
    assert (premier.nb_recuperees, premier.nb_nouvelles, premier.nb_doublons) == (2, 2, 0)

    second = lancer_scan(session, SearchQuery(), sources=["a"])
    assert (second.nb_recuperees, second.nb_nouvelles, second.nb_doublons) == (2, 0, 2)
    assert _compter_offres(session) == 2


def test_le_scan_n_appelle_jamais_le_llm(session, sources):
    sources["a"] = _source("a", [_offre()])
    assert lancer_scan(session, SearchQuery(), sources=["a"]).nb_appels_llm == 0


def test_la_meme_annonce_sur_deux_sources_ne_compte_qu_une_fois(session, sources):
    """Identifiants différents, contenu identique : c'est le hash qui tranche."""
    sources["a"] = _source("a", [_offre(source="a", identifiant="A1")])
    sources["b"] = _source("b", [_offre(source="b", identifiant="B9")])

    scan = lancer_scan(session, SearchQuery(), sources=["a", "b"])
    assert scan.nb_recuperees == 2
    assert scan.nb_nouvelles == 1
    assert scan.nb_doublons == 1
    assert _compter_offres(session) == 1


def test_doublon_a_l_interieur_d_un_meme_lot(session, sources):
    sources["a"] = _source("a", [_offre(identifiant="1"), _offre(identifiant="2")])
    scan = lancer_scan(session, SearchQuery(), sources=["a"])
    assert (scan.nb_nouvelles, scan.nb_doublons) == (1, 1)


def test_un_meme_source_id_republiee_avec_un_autre_texte(session, sources):
    """Le second filet : (source, source_id) attrape ce que le hash laisse passer."""
    sources["a"] = _source("a", [_offre(identifiant="1")])
    lancer_scan(session, SearchQuery(), sources=["a"])

    sources["a"] = _source("a", [_offre(identifiant="1", description="Texte remanié.")])
    scan = lancer_scan(session, SearchQuery(), sources=["a"])
    assert (scan.nb_nouvelles, scan.nb_doublons) == (0, 1)


# --- Isolation des pannes --------------------------------------------------


def test_une_source_en_panne_n_empeche_pas_les_autres(session, sources):
    sources["ok"] = _source("ok", [_offre(source="ok")])
    sources["ko"] = _source("ko", erreur=ErreurConnecteur("503 chez le fournisseur"))

    scan = lancer_scan(session, SearchQuery(), sources=["ko", "ok"])
    assert scan.nb_nouvelles == 1
    assert scan.statut == StatutScan.PARTIEL.value
    assert [e["source"] for e in scan.erreurs] == ["ko"]
    assert scan.erreurs[0]["type"] == "panne"


def test_un_bug_inattendu_dans_un_connecteur_ne_tue_pas_le_scan(session, sources):
    sources["ok"] = _source("ok", [_offre(source="ok")])
    sources["bug"] = _source("bug", erreur=ZeroDivisionError("division by zero"))

    scan = lancer_scan(session, SearchQuery(), sources=["bug", "ok"])
    assert scan.nb_nouvelles == 1
    assert scan.erreurs[0]["type"] == "inattendu"
    assert "ZeroDivisionError" in scan.erreurs[0]["erreur"]


def test_source_non_configuree_n_est_pas_traitee_comme_une_panne(session, sources):
    sources["a"] = _source("a", erreur=ConnecteurNonConfigure("Identifiants absents dans .env"))
    scan = lancer_scan(session, SearchQuery(), sources=["a"])
    assert scan.erreurs[0]["type"] == "non_configure"


def test_toutes_les_sources_en_panne_donne_un_echec(session, sources):
    sources["a"] = _source("a", erreur=ErreurConnecteur("boum"))
    sources["b"] = _source("b", erreur=ErreurConnecteur("boum"))
    scan = lancer_scan(session, SearchQuery(), sources=["a", "b"])
    assert scan.statut == StatutScan.ECHEC.value


def test_aucune_source_active_est_un_echec_pas_un_succes_vide(session, sources):
    scan = lancer_scan(session, SearchQuery(), sources=[])
    assert scan.statut == StatutScan.ECHEC.value


# --- Filtres ---------------------------------------------------------------


def test_les_offres_hors_pays_sont_rejetees(session, sources):
    sources["a"] = _source("a", [
        _offre(identifiant="1", pays="France"),
        _offre(identifiant="2", pays="Allemagne", titre="Analyst"),
    ])
    scan = lancer_scan(session, SearchQuery(pays=["France"]), sources=["a"])
    assert (scan.nb_nouvelles, scan.nb_rejetees) == (1, 1)


def test_les_contrats_non_souhaites_sont_rejetes(session, sources):
    sources["a"] = _source("a", [
        _offre(identifiant="1", contrat="CDI"),
        _offre(identifiant="2", contrat="Intérim", titre="Gestionnaire back office"),
    ])
    scan = lancer_scan(session, SearchQuery(contrats=["CDI", "CDD"]), sources=["a"])
    assert (scan.nb_nouvelles, scan.nb_rejetees) == (1, 1)


def test_les_nouvelles_offres_sont_marquees_non_vues(session, sources):
    """Alimente le badge « X nouvelles offres » de l'étape 9."""
    sources["a"] = _source("a", [_offre()])
    lancer_scan(session, SearchQuery(), sources=["a"])
    assert session.exec(select(Offer)).first().vue is False
