"""L'API des scans, vue depuis l'interface.

Ces tests tournent sur la configuration réelle du projet : France Travail est
active dans config.yaml mais sans identifiants dans .env. C'est exactement l'état
d'une installation neuve — le comportement doit être lisible, pas un plantage.
"""


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
