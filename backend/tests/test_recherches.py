"""Les recherches enregistrées.

Un profil ne se résume pas à un jeu de mots-clés : « analyste risques »,
« middle office » et « V.I.E finance » se cherchent en même temps, parfois sur
des pays différents.
"""

import pytest
from sqlmodel import Session

from app.config import reglages
from app.connectors.base import BaseConnector, RawOffer, SearchQuery
from app.models import Profile, Recherche
from app.services.scan import lancer_scan, requetes_actives


def _creer(client, **kw):
    base = {"nom": "Analyste risques", "mots_cles": ["analyste risques"]}
    return client.post("/api/recherches", json={**base, **kw})


# --- API ---------------------------------------------------------------------


def test_creation_et_lecture(client):
    reponse = _creer(client, pays=["France", "Luxembourg"], contrats=["CDI"])
    assert reponse.status_code == 201
    recherche = reponse.json()
    assert recherche["nom"] == "Analyste risques"
    assert recherche["pays"] == ["France", "Luxembourg"]
    assert client.get("/api/recherches").json()[0]["id"] == recherche["id"]


def test_deux_recherches_ne_peuvent_pas_porter_le_meme_nom(client):
    _creer(client)
    doublon = _creer(client, mots_cles=["autre chose"])
    assert doublon.status_code == 409
    assert "existe déjà" in doublon.json()["detail"]


def test_un_pays_inconnu_est_refuse(client):
    assert _creer(client, pays=["Atlantide"]).status_code == 422


def test_un_contrat_inconnu_est_refuse(client):
    assert _creer(client, contrats=["Portage"]).status_code == 422


def test_un_nom_vide_est_refuse(client):
    assert _creer(client, nom="   ").status_code == 422


def test_desactiver_une_recherche(client):
    identifiant = _creer(client).json()["id"]
    maj = client.patch(f"/api/recherches/{identifiant}", json={"active": False})
    assert maj.json()["active"] is False


def test_supprimer_une_recherche(client):
    identifiant = _creer(client).json()["id"]
    assert client.delete(f"/api/recherches/{identifiant}").status_code == 204
    assert client.get("/api/recherches").json() == []


# --- Construction des requêtes ----------------------------------------------


def test_sans_recherche_on_retombe_sur_le_profil(session):
    """L'application reste utilisable avant qu'une recherche ait été créée."""
    session.add(Profile(pays_acceptes=["Belgique"], contrats_acceptes=["V.I.E"]))
    session.commit()

    requetes = requetes_actives(session, reglages())
    assert len(requetes) == 1
    assert requetes[0].pays == ["Belgique"]


def test_les_recherches_actives_deviennent_autant_de_requetes(session):
    session.add(Profile(pays_acceptes=["France"]))
    for i, nom in enumerate(["Analyste", "Middle office", "V.I.E"]):
        session.add(Recherche(nom=nom, mots_cles=[nom.lower()], ordre=i))
    session.commit()

    requetes = requetes_actives(session, reglages())
    assert [r.mots_cles[0] for r in requetes] == ["analyste", "middle office", "v.i.e"]


def test_une_recherche_desactivee_n_est_pas_jouee(session):
    session.add(Profile())
    session.add(Recherche(nom="Active", mots_cles=["a"]))
    session.add(Recherche(nom="En pause", mots_cles=["b"], active=False))
    session.commit()

    assert [r.mots_cles[0] for r in requetes_actives(session, reglages())] == ["a"]


def test_une_recherche_sans_pays_herite_de_ceux_du_profil(session):
    """Une recherche n'a pas à répéter les pays acceptés si elle ne les restreint pas."""
    session.add(Profile(pays_acceptes=["France", "Belgique"]))
    session.add(Recherche(nom="Générale", mots_cles=["finance"]))
    session.commit()

    assert requetes_actives(session, reglages())[0].pays == ["France", "Belgique"]


def test_une_recherche_avec_ses_propres_pays_les_impose(session):
    session.add(Profile(pays_acceptes=["France"]))
    session.add(Recherche(nom="V.I.E monde", mots_cles=["vie"], pays=["Singapour"]))
    session.commit()

    assert requetes_actives(session, reglages())[0].pays == ["Singapour"]
