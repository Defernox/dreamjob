"""L'API du profil, vue depuis l'interface."""

from .conftest import FIXTURES


def test_profil_vide_est_cree_au_premier_appel(client):
    """Pas de 404 au démarrage : l'écran doit pouvoir s'ouvrir sur un profil vierge."""
    r = client.get("/api/profil")
    assert r.status_code == 200
    profil = r.json()
    assert profil["id"] >= 1
    assert profil["skills"] == []
    assert profil["contrats_acceptes"] == []


def test_enregistrement_et_relecture(client):
    envoi = {
        "prenom": "Camille", "nom": "Dupont",
        "titre_vise": "Cheffe de projet digital",
        "secteurs": ["communication digitale"],
        "langues": [{"code": "fr", "libelle": "Français", "niveau": "natif"}],
        "skills": [{"nom": "Instagram", "niveau": "courant", "ancree": True}],
        "experiences": [{"entreprise": "Fabrique Lumière", "poste": "Chargée de com"}],
        "formations": [{"etablissement": "Université de Lyon", "diplome": "Master"}],
        "pays_acceptes": ["France", "Belgique"],
        "contrats_acceptes": ["CDI", "CDD"],
    }
    assert client.put("/api/profil", json=envoi).status_code == 200

    profil = client.get("/api/profil").json()
    assert profil["prenom"] == "Camille"
    assert profil["skills"][0]["ancree"] is True
    # L'ordre des contrats porte la préférence : il ne doit pas être trié.
    assert profil["contrats_acceptes"] == ["CDI", "CDD"]


def test_ordre_des_contrats_preserve(client):
    client.put("/api/profil", json={"contrats_acceptes": ["V.I.E", "CDI", "Stage"]})
    assert client.get("/api/profil").json()["contrats_acceptes"] == ["V.I.E", "CDI", "Stage"]


def test_contrat_inconnu_refuse(client):
    r = client.put("/api/profil", json={"contrats_acceptes": ["Portage salarial"]})
    assert r.status_code == 422
    assert "Portage salarial" in r.text


def test_import_refuse_un_format_non_supporte(client):
    r = client.post(
        "/api/profil/importer",
        files={"fichier": ("notes.txt", b"du texte", "text/plain")},
    )
    assert r.status_code == 400
    assert ".docx" in r.json()["detail"]


def test_import_sans_llm_repond_503_et_le_dit(client, monkeypatch):
    """Sans clé API, l'utilisateur doit comprendre pourquoi, pas voir une erreur 500."""
    from app.llm.client import ClientLlm

    monkeypatch.setattr(ClientLlm, "disponible", property(lambda self: False))
    r = client.post(
        "/api/profil/importer",
        files={"fichier": ("cv_exemple.docx", (FIXTURES / "cv_exemple.docx").read_bytes(),
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_import_remplit_le_profil_sans_ecraser_les_preferences(client, monkeypatch):
    """Un CV ne contient pas les pays/contrats acceptés : l'import ne doit pas les effacer."""
    from app.api import profile as api_profil
    from app.schemas.profile import ProfilStructure, Skill

    client.put("/api/profil", json={
        "pays_acceptes": ["France", "Suisse"],
        "contrats_acceptes": ["CDI"],
    })

    faux_profil = ProfilStructure(
        prenom="Camille", nom="Dupont",
        titre_vise="Cheffe de projet digital",
        skills=[Skill(nom="Instagram", ancree=True)],
    )
    # On patche le nom tel qu'il est lié dans le routeur, pas dans son module
    # d'origine : l'import par nom fige la référence.
    monkeypatch.setattr(
        api_profil, "importer_cv",
        lambda chemin, session, forcer=False: (faux_profil, False, "modele-test", 404),
    )

    r = client.post(
        "/api/profil/importer",
        files={"fichier": ("cv_exemple.docx", (FIXTURES / "cv_exemple.docx").read_bytes(),
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert r.status_code == 200, r.text
    profil = r.json()["profil"]
    assert profil["prenom"] == "Camille"
    assert profil["pays_acceptes"] == ["France", "Suisse"]   # conservés
    assert profil["contrats_acceptes"] == ["CDI"]            # conservés
