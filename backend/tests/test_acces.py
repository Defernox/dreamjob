"""Le verrou de l'application hébergée.

En local, rien ne change : l'API n'écoute que sur 127.0.0.1. En mode serveur,
tout `/api/` est fermé sans session — sauf de quoi se connecter.
"""

import pytest
from sqlmodel import select

from app.models import SessionUtilisateur
from app.services.acces import (
    COOKIE,
    Limiteur,
    MotDePasseTropCourt,
    creer_utilisateur,
    hacher,
    verifier,
)

MOT_DE_PASSE = "une phrase assez longue"


@pytest.fixture
def serveur(client, monkeypatch):
    # Le cookie de session est `Secure` : comme un navigateur, le client de test
    # ne le renvoie qu'en HTTPS. En HTTP, la connexion « réussit » et la requête
    # suivante arrive sans session — c'est le comportement voulu.
    client.base_url = "https://testserver"
    monkeypatch.setenv("DREAMJOB_MODE", "serveur")
    from app.services import acces
    monkeypatch.setattr(acces, "limiteur", Limiteur())
    import app.api.acces as route
    monkeypatch.setattr(route, "limiteur", acces.limiteur)


@pytest.fixture
def compte(session):
    return creer_utilisateur(session, "Moi@Exemple.fr", MOT_DE_PASSE)


def _connecter(client, email="moi@exemple.fr", mot_de_passe=MOT_DE_PASSE):
    return client.post("/api/acces/connexion", json={"email": email, "mot_de_passe": mot_de_passe})


# --- Le verrou ---------------------------------------------------------------


def test_en_local_rien_n_est_verrouille(client):
    assert client.get("/api/offres").status_code == 200
    assert client.get("/api/acces/etat").json()["connexion_requise"] is False


def test_sur_le_serveur_tout_est_ferme_sans_session(client, serveur):
    for route in ("/api/offres", "/api/profil", "/api/candidatures", "/api/reglages"):
        assert client.get(route).status_code == 401, route


def test_de_quoi_se_connecter_reste_ouvert(client, serveur):
    assert client.get("/api/sante").status_code == 200
    etat = client.get("/api/acces/etat").json()
    assert etat == {"connexion_requise": True, "connecte": False, "email": None,
                    "proprietaire": False}


def test_une_fois_connecte_l_api_repond(client, serveur, compte):
    reponse = _connecter(client)
    assert reponse.status_code == 200
    assert client.get("/api/offres").status_code == 200
    assert client.get("/api/acces/etat").json()["email"] == "moi@exemple.fr"


def test_le_cookie_est_illisible_par_la_page_et_reserve_au_https(client, serveur, compte):
    entete = _connecter(client).headers["set-cookie"].lower()
    assert "httponly" in entete and "secure" in entete and "samesite=lax" in entete


def test_la_deconnexion_ferme_vraiment_la_session(client, serveur, compte, session):
    _connecter(client)
    jeton = client.cookies.get(COOKIE)
    client.post("/api/acces/deconnexion")
    client.cookies.set(COOKIE, jeton)          # un jeton recopié ne rouvre rien
    assert client.get("/api/offres").status_code == 401


# --- La connexion -------------------------------------------------------------


@pytest.mark.parametrize("email, mot_de_passe", [
    ("moi@exemple.fr", "mauvais mot de passe"),
    ("inconnu@exemple.fr", MOT_DE_PASSE),
])
def test_un_echec_ne_dit_pas_si_l_adresse_existe(client, serveur, compte, email, mot_de_passe):
    reponse = _connecter(client, email, mot_de_passe)
    assert reponse.status_code == 401
    assert reponse.json()["detail"] == "Adresse ou mot de passe incorrect."


def test_l_adresse_est_insensible_a_la_casse(client, serveur, compte):
    assert _connecter(client, "  MOI@exemple.FR ").status_code == 200


def test_les_essais_repetes_sont_bloques(client, serveur, compte):
    for _ in range(10):
        _connecter(client, mot_de_passe="faux mot de passe !")
    # Même le bon mot de passe est refusé tant que la fenêtre court.
    assert _connecter(client).status_code == 429


# --- Ce qui est stocké --------------------------------------------------------


def test_le_mot_de_passe_n_est_jamais_stocke(compte):
    assert MOT_DE_PASSE not in compte.mot_de_passe
    assert compte.mot_de_passe.startswith("scrypt$")


def test_le_jeton_de_session_n_est_pas_stocke_en_clair(client, serveur, compte, session):
    _connecter(client)
    jeton = client.cookies.get(COOKIE)
    empreintes = [s.empreinte for s in session.exec(select(SessionUtilisateur)).all()]
    assert empreintes and jeton not in empreintes


def test_deux_hachages_du_meme_mot_de_passe_different():
    """Le sel : deux comptes au même mot de passe n'ont pas la même empreinte."""
    assert hacher(MOT_DE_PASSE) != hacher(MOT_DE_PASSE)
    assert verifier(MOT_DE_PASSE, hacher(MOT_DE_PASSE))


def test_un_mot_de_passe_court_est_refuse():
    with pytest.raises(MotDePasseTropCourt):
        hacher("court")


# --- L'interface servie par l'API --------------------------------------------


def test_un_chemin_ne_peut_pas_sortir_du_dossier_de_l_interface(tmp_path, monkeypatch):
    """« /../../.env » doit renvoyer la page d'accueil, jamais le fichier."""
    from fastapi.testclient import TestClient

    import app.main as principal

    if not principal.FRONT.is_dir():
        pytest.skip("interface non compilée (frontend/dist absent)")
    # Le démarrage neutralisé, comme dans la fixture `client` : sans cela, ce
    # test créait les nouvelles tables dans la VRAIE base et y cherchait le
    # dernier scan.
    for nom in ("creer_tables", "sauvegarder", "demarrer_planificateur",
                "arreter_planificateur", "checkpoint"):
        monkeypatch.setattr(principal, nom, lambda *a, **kw: None)
    with TestClient(principal.app) as c:
        reponse = c.get("/..%2F..%2F.env")
        assert "ANTHROPIC" not in reponse.text
