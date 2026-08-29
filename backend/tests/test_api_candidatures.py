"""Les candidatures — ce que déclenche le bouton « Postuler »."""

import pytest
from sqlmodel import Session

from app.models import Offer


@pytest.fixture
def offre(engine):
    with Session(engine) as s:
        o = Offer(source="france_travail", source_id="1", hash="h1",
                  titre="Analyste risques de crédit", entreprise="Banque A",
                  pays="France", type_contrat="CDI", score=88.0,
                  url="https://exemple.test/offre/1")
        s.add(o)
        s.commit()
        s.refresh(o)
        return o.id


def test_postuler_cree_une_candidature_envoyee(client, offre):
    reponse = client.post("/api/candidatures", json={"offer_id": offre})
    assert reponse.status_code == 201

    candidature = reponse.json()
    assert candidature["statut"] == "Envoyée"
    # Les infos de l'offre voyagent avec : le tableau de suivi se lit sans jointure.
    assert candidature["titre"] == "Analyste risques de crédit"
    assert candidature["entreprise"] == "Banque A"
    assert candidature["score"] == 88.0


def test_double_clic_sur_postuler_ne_cree_pas_de_doublon(client, offre):
    premiere = client.post("/api/candidatures", json={"offer_id": offre}).json()
    seconde = client.post("/api/candidatures", json={"offer_id": offre}).json()
    assert premiere["id"] == seconde["id"]
    assert len(client.get("/api/candidatures").json()) == 1


def test_postuler_sur_une_offre_inexistante(client):
    reponse = client.post("/api/candidatures", json={"offer_id": 9999})
    assert reponse.status_code == 404


def test_statut_inconnu_refuse(client, offre):
    reponse = client.post("/api/candidatures", json={"offer_id": offre, "statut": "Peut-être"})
    assert reponse.status_code == 422
    assert "Statut inconnu" in reponse.text


def test_changer_de_statut(client, offre):
    identifiant = client.post("/api/candidatures", json={"offer_id": offre}).json()["id"]
    maj = client.patch(f"/api/candidatures/{identifiant}", json={"statut": "Entretien"}).json()
    assert maj["statut"] == "Entretien"


def test_notes_et_deadline(client, offre):
    identifiant = client.post("/api/candidatures", json={"offer_id": offre}).json()["id"]
    maj = client.patch(f"/api/candidatures/{identifiant}",
                       json={"notes": "Relancer lundi", "deadline": "2026-09-15"}).json()
    assert maj["notes"] == "Relancer lundi"
    assert maj["deadline"] == "2026-09-15"


def test_supprimer_une_candidature(client, offre):
    identifiant = client.post("/api/candidatures", json={"offer_id": offre}).json()["id"]
    assert client.delete(f"/api/candidatures/{identifiant}").status_code == 204
    assert client.get("/api/candidatures").json() == []


def test_l_offre_signale_ensuite_qu_elle_a_une_candidature(client, offre):
    assert client.get(f"/api/offres/{offre}").json()["a_candidature"] is False
    client.post("/api/candidatures", json={"offer_id": offre})
    assert client.get(f"/api/offres/{offre}").json()["a_candidature"] is True
