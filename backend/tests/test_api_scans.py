"""L'API des scans, vue depuis l'interface.

Ces tests tournent sur la configuration réelle du projet : France Travail est
active dans config.yaml mais sans identifiants dans .env. C'est exactement l'état
d'une installation neuve — le comportement doit être lisible, pas un plantage.

La recherche se déroule en arrière-plan ; ici, elle est déroulée sur place
(`sur_place`), pour lire son résultat dans la réponse.
"""

import pytest
from sqlmodel import select

from app.api import scans as api_scans
from app.models import ScanRun
from app.models.enums import StatutScan


@pytest.fixture(autouse=True)
def sur_place(monkeypatch):
    lancees = []

    def demarrer(cible, *arguments):
        lancees.append(arguments)
        cible(*arguments)

    monkeypatch.setattr(api_scans, "_demarrer", demarrer)
    return lancees


def test_la_recherche_part_en_arriere_plan_et_se_suit(client, monkeypatch):
    """Plusieurs minutes avec les sites des employeurs : la réponse n'attend
    pas, elle rend le scan « en cours », que l'interface relit."""
    monkeypatch.setattr(api_scans, "_demarrer", lambda cible, *a: None)
    scan = client.post("/api/scans", json={"sources": ["france_travail"]}).json()
    assert scan["statut"] == StatutScan.EN_COURS.value
    assert client.get(f"/api/scans/{scan['id']}").json()["statut"] == StatutScan.EN_COURS.value
    deuxieme = client.post("/api/scans", json={"sources": ["france_travail"]})
    assert deuxieme.status_code == 409, "une recherche à la fois"


def test_la_recherche_n_est_close_qu_une_fois_ses_offres_notees(client, monkeypatch):
    """Close avant, l'interface relisait aussitôt la liste et montrait les
    nouveautés sans note, dans le désordre."""
    from sqlmodel import Session

    from app import scheduler

    pendant = []

    def rescorer(moteur, utilisateur_id, *, forcer):
        with Session(moteur) as s:
            pendant.append(s.exec(select(ScanRun)).one().statut)

    monkeypatch.setattr(scheduler, "rescorer", rescorer)
    scan = client.post("/api/scans", json={"sources": ["france_travail"]}).json()
    assert pendant == [StatutScan.EN_COURS.value], "noté pendant que l'interface attend encore"
    assert client.get(f"/api/scans/{scan['id']}").json()["statut"] == StatutScan.ECHEC.value


def test_l_historique_peut_ignorer_la_veille(client, session):
    """Une passe de veille toutes les demi-heures : sans ce filtre, elle cachait
    le scan du matin au diagnostic, et l'écran Offres la reprenait pour une
    recherche de l'utilisateur."""
    session.add(ScanRun(declenche_par="planifie", statut=StatutScan.PARTIEL.value))
    session.commit()
    session.add(ScanRun(declenche_par="veille", statut=StatutScan.EN_COURS.value))
    session.commit()
    assert client.get("/api/scans?limite=1").json()[0]["declenche_par"] == "veille"
    [dernier] = client.get("/api/scans?limite=1&avec_veille=false").json()
    assert dernier["declenche_par"] == "planifie"


def test_un_scan_interrompu_par_un_arret_est_clos_au_demarrage(session):
    from app.services.scan import clore_les_interrompus

    session.add(ScanRun(statut=StatutScan.EN_COURS.value))
    session.commit()
    assert clore_les_interrompus(session) == 1
    [scan] = session.exec(select(ScanRun)).all()
    assert scan.statut == StatutScan.ECHEC.value and "interrompu" in scan.erreurs[0]["erreur"]


def test_un_scan_sans_identifiants_repond_200_et_explique(client):
    # Source nommée explicitement : le test ne doit pas dépendre de la liste
    # des sources actives dans config.yaml, qui évolue.
    reponse = client.post("/api/scans", json={"sources": ["france_travail"]})
    assert reponse.status_code == 200

    scan = reponse.json()
    assert scan["statut"] == "échec"
    assert scan["nb_recuperees"] == 0
    assert scan["nb_appels_llm"] == 0

    erreur = scan["erreurs"][0]
    assert erreur["source"] == "france_travail"
    assert erreur["type"] == "non_configure"
    assert "FRANCE_TRAVAIL_CLIENT_ID" in erreur["erreur"]


def test_la_requete_de_l_interface_surcharge_config_yaml(client):
    reponse = client.post("/api/scans", json={
        "mots_cles": ["analyste", "risques"],
        "max_offres": 25,
        "departement": "75",
    })
    requete = reponse.json()["requete"]
    assert requete["mots_cles"] == ["analyste", "risques"]
    assert requete["max_offres"] == 25
    assert requete["departement"] == "75"
    # Les champs non fournis gardent la valeur de config.yaml.
    assert requete["pays"] == ["France"]


def test_historique_des_scans(client):
    client.post("/api/scans")
    client.post("/api/scans")

    historique = client.get("/api/scans").json()
    assert len(historique) == 2
    # Le plus récent d'abord.
    assert historique[0]["started_at"] >= historique[1]["started_at"]


def test_detail_d_un_scan(client):
    identifiant = client.post("/api/scans").json()["id"]
    assert client.get(f"/api/scans/{identifiant}").status_code == 200


def test_scan_inexistant(client):
    reponse = client.get("/api/scans/9999")
    assert reponse.status_code == 404
    assert reponse.json()["detail"] == "Scan introuvable."


def test_scan_limite_a_une_source_choisie(client):
    scan = client.post("/api/scans", json={"sources": ["france_travail"]}).json()
    assert scan["sources"] == ["france_travail"]


def test_liste_de_sources_vide_est_refusee(client):
    """Sans ce garde-fou, une liste vide retomberait en silence sur les valeurs
    par défaut — l'utilisateur croirait avoir restreint sa recherche."""
    reponse = client.post("/api/scans", json={"sources": []})
    assert reponse.status_code == 400
    assert "au moins une source" in reponse.json()["detail"]
