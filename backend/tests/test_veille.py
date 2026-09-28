"""La veille : repérer une offre dans l'heure où elle paraît, et alerter.

Ce que ces tests protègent : une offre verte déclenche UNE alerte, jamais deux ;
les sources au quota serré ne sont pas interrogées ; la veille ne se fait pas
passer pour le scan du matin ; et elle ratisse plus large que les seules
recherches enregistrées.
"""

from datetime import timedelta

import httpx
import pytest
from sqlmodel import select

from app.config import reglages
from app.connectors import registry
from app.connectors.base import BaseConnector, RawOffer
from app.models import Profile, ScanRun, ScoreOffre
from app.models.base import maintenant
from app.services import notification
from app.services.acces import proprietaire
from app.services.scan import dernier_scan_abouti
from app.services.veille import (
    DECLENCHEUR,
    dans_la_plage,
    demandes_de_veille,
    faire_le_menage,
    veiller,
)

DESCRIPTION = ("Au sein de la direction des risques, vous évaluez la solvabilité des "
               "contreparties, suivez les encours et analysez les dossiers de crédit.")


@pytest.fixture
def moi(session):
    """Le propriétaire, avec un profil qui rend verte une offre d'analyste crédit."""
    compte = proprietaire(session)
    session.add(Profile(
        utilisateur_id=compte.id, titre_vise="Analyste risques de crédit", annees_experience=3,
        ville="Paris", pays="France",
        skills=[{"nom": "Risque de crédit", "ancree": True},
                {"nom": "Analyse financière", "ancree": True}],
        secteurs=["Banque et assurance"],
        experiences=[{"poste": "Chargé d'affaires entreprises", "fin": "2025",
                      "description": "Analyse de la solvabilité des entreprises.",
                      "tags": ["Crédit"]}],
        formations=[{"diplome": "Master 2 Finance"}],
        langues=[{"code": "fr", "niveau": "natif"}],
        pays_acceptes=["France"], contrats_acceptes=["CDI"],
    ))
    session.commit()
    return compte.id


def _brute(source, identifiant, titre="Analyste risques de crédit"):
    return RawOffer(source=source, source_id=identifiant, titre=titre, entreprise="Banque",
                    lieu="75 - Paris", pays="France", type_contrat="CDI",
                    date_publication=maintenant() - timedelta(minutes=25),
                    description_brute=DESCRIPTION)


@pytest.fixture
def sources(monkeypatch):
    """Trois fausses sources, qui rendent ce qu'on leur confie et notent les appels."""
    appels: dict[str, list] = {"france_travail": [], "civiweb": [], "adzuna": []}
    stock: dict[str, list[RawOffer]] = {cle: [] for cle in appels}

    def fabrique(cle):
        class Fausse(BaseConnector):
            def fetch(self, query):
                appels[cle].append(query)
                return list(stock[cle])
        Fausse.cle = Fausse.libelle = cle
        return Fausse

    monkeypatch.setattr(registry, "CONNECTEURS", {c: fabrique(c) for c in appels})
    return appels, stock


@pytest.fixture
def envois(monkeypatch):
    partis = []

    def faux_post(url, content, headers, timeout):
        partis.append({"url": url, "corps": content.decode("utf-8"), "entetes": headers})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(notification.httpx, "post", faux_post)
    monkeypatch.setenv("NTFY_SUJET", "sujet-de-test")
    monkeypatch.setenv("DREAMJOB_URL", "https://dreamjob.exemple.ts.net")
    return partis


# --- Ce que la veille cherche ------------------------------------------------------


def test_la_veille_ne_cherche_que_les_offres_du_jour(session, moi):
    demandes = demandes_de_veille(session, reglages())
    assert demandes
    assert all(d.requete.publiee_depuis_jours == 1 for d in demandes)


def test_la_veille_ratisse_plus_large_que_les_recherches(session, moi):
    """Quand il ne s'agit que de repérer les nouveautés, on élargit : titre
    visé, postes, mots-clés d'expérience et secteurs deviennent des requêtes."""
    mots = [" ".join(d.requete.mots_cles) for d in demandes_de_veille(session, reglages())]
    assert "Analyste risques de crédit" in mots
    assert "Chargé d'affaires entreprises" in mots
    assert "Crédit" in mots
    assert "Banque et assurance" in mots


def test_un_diplome_n_est_pas_une_requete_de_veille(session, moi):
    mots = [" ".join(d.requete.mots_cles) for d in demandes_de_veille(session, reglages())]
    assert not any("Master" in m for m in mots)


def test_une_requete_du_cv_ne_double_pas_une_recherche(session, moi):
    from app.models import Recherche

    session.add(Recherche(utilisateur_id=moi, nom="Crédit", mots_cles=["crédit"]))
    session.commit()
    mots = [" ".join(d.requete.mots_cles).lower() for d in demandes_de_veille(session, reglages())]
    assert mots.count("crédit") == 1


def test_le_nombre_de_requetes_du_cv_est_plafonne(session, moi, monkeypatch):
    monkeypatch.setattr(reglages().veille, "requetes_du_cv_max", 1)
    demandes = demandes_de_veille(session, reglages())
    assert len(demandes) == 2      # la requête de repli du profil, et une seule du CV


def test_ni_adzuna_ni_dogfinance_ne_sont_interroges(session, moi, sources, envois):
    """Adzuna : 2 500 appels par mois, déjà aux trois cinquièmes. DogFinance :
    quarante pages par jour, pour une raison juridique."""
    appels, _ = sources
    veiller(session, reglages())
    assert appels["france_travail"] and appels["civiweb"]
    assert appels["adzuna"] == []


# --- L'alerte ------------------------------------------------------------------------


def test_une_offre_verte_part_aussitot_et_une_seule_fois(session, moi, sources, envois):
    _, stock = sources
    stock["france_travail"] = [_brute("france_travail", "1")]

    veiller(session, reglages())
    assert len(envois) == 1
    envoi = envois[0]
    assert envoi["entetes"]["Title"].decode("utf-8").endswith("Analyste risques de crédit")
    assert "publiée il y a" in envoi["corps"]
    # Un clic ouvre la fiche, pas la liste : c'est là qu'on décide.
    assert envoi["entetes"]["Click"].endswith(f"/offres/{session.exec(select(ScoreOffre)).one().offer_id}")

    veiller(session, reglages())            # l'offre est toujours en ligne
    assert len(envois) == 1, "déjà signalée : pas de seconde alerte"


def test_une_offre_qui_n_est_pas_verte_ne_sonne_pas(session, moi, sources, envois):
    _, stock = sources
    stock["france_travail"] = [_brute("france_travail", "1", titre="Boulanger")]
    veiller(session, reglages())
    assert envois == []


def test_les_alertes_du_jour_sont_plafonnees(session, moi, sources, envois, monkeypatch):
    """Une sonnerie toutes les dix minutes apprend à les ignorer toutes : au-delà
    du plafond, les offres attendent le résumé du matin."""
    monkeypatch.setattr(reglages().veille, "alertes_par_jour_max", 2)
    _, stock = sources
    stock["france_travail"] = [_brute("france_travail", str(i)) for i in range(3)]
    stock["france_travail"][1].description_brute += " Poste à Paris."
    stock["france_travail"][2].description_brute += " Poste à Paris, en CDI."

    veiller(session, reglages())
    assert len(envois) == 2

    # Le résumé du matin reprend la troisième, et elle seule.
    envois.clear()
    assert notification.notifier(session, maintenant() - timedelta(days=1)) == 1
    assert envois[0]["entetes"]["Title"].decode("utf-8") == "1 nouvelle offre verte"


def test_le_resume_du_matin_ne_repete_pas_une_alerte(session, moi, sources, envois):
    _, stock = sources
    stock["france_travail"] = [_brute("france_travail", "1")]
    veiller(session, reglages())
    envois.clear()
    assert notification.notifier(session, maintenant() - timedelta(days=1)) == 0


# --- La veille n'est pas le scan du matin --------------------------------------------------


def test_une_veille_ne_compte_pas_comme_derniere_recherche(session, moi, sources, envois):
    """Comptée, elle aurait réduit le badge « nouvelles » à la dernière
    demi-heure, et empêché le rattrapage du matin."""
    veiller(session, reglages())
    assert session.exec(select(ScanRun).where(ScanRun.declenche_par == DECLENCHEUR)).first()
    assert dernier_scan_abouti(session) is None


def test_les_vieilles_veilles_sont_oubliees(session, moi):
    ancien = maintenant() - timedelta(days=30)
    session.add(ScanRun(declenche_par=DECLENCHEUR, statut="terminé", started_at=ancien))
    session.add(ScanRun(declenche_par="planifie", statut="terminé", started_at=ancien))
    session.commit()
    assert faire_le_menage(session, reglages()) == 1
    assert [s.declenche_par for s in session.exec(select(ScanRun)).all()] == ["planifie"]


def test_pas_de_veille_la_nuit():
    r = reglages()
    assert dans_la_plage(r, 10)
    assert not dans_la_plage(r, 3)
    assert not dans_la_plage(r, r.veille.heure_fin)


def test_une_veille_ne_tourne_pas_pendant_un_scan(session, monkeypatch):
    from app import scheduler

    appelee = []
    monkeypatch.setattr(scheduler, "veiller", lambda *a: appelee.append(1))
    monkeypatch.setattr(scheduler, "dans_la_plage", lambda *a: True)
    monkeypatch.setattr(scheduler, "engine", session.get_bind())
    with scheduler._VERROU_SCAN:
        scheduler.executer_veille()
    assert appelee == []
    scheduler.executer_veille()
    assert appelee == [1]
