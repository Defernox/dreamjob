"""Le client HTTP partagé : les garanties qu'on doit aux sources qu'on interroge.

Limitation de débit, backoff, cache : si ça casse ici, c'est toute l'application
qui devient impolie avec des sites tiers.
"""

import time

import httpx
import pytest

from app.connectors.http import ClientHttp, ErreurHttp


def _client(reponses, tmp_path=None, **kw):
    """ClientHttp branché sur un transport simulé qui rejoue `reponses`."""
    restantes = list(reponses)
    appels = []

    def repondre(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        suite = restantes.pop(0) if len(restantes) > 1 else restantes[0]
        if isinstance(suite, Exception):
            raise suite
        return suite

    c = ClientHttp(
        user_agent="DreamJob/test",
        dossier_cache=tmp_path,
        **{"requetes_par_seconde": 1000, **kw},
    )
    c._client = httpx.Client(transport=httpx.MockTransport(repondre))
    c.appels = appels
    return c


def _ok(charge=None):
    return httpx.Response(200, json=charge if charge is not None else {"ok": True})


# --- Politesse -------------------------------------------------------------


def test_user_agent_explicite_sur_chaque_requete():
    c = _client([_ok()])
    c.get("https://exemple.test/a", utiliser_cache=False)
    assert c.appels[0].headers["user-agent"] == "DreamJob/test"


def test_limitation_de_debit_par_hote():
    c = _client([_ok()], requetes_par_seconde=10)     # 100 ms entre deux appels
    depart = time.monotonic()
    for _ in range(3):
        c.get("https://exemple.test/a", utiliser_cache=False)
    ecoule = time.monotonic() - depart
    assert ecoule >= 0.2, "les requêtes ne sont pas espacées"


def test_la_limitation_est_par_hote_pas_globale():
    """Interroger deux sources différentes ne doit pas les ralentir l'une l'autre."""
    c = _client([_ok()], requetes_par_seconde=5)      # 200 ms
    depart = time.monotonic()
    c.get("https://source-a.test/x", utiliser_cache=False)
    c.get("https://source-b.test/x", utiliser_cache=False)
    assert time.monotonic() - depart < 0.15


# --- Reprise sur erreur ----------------------------------------------------


def test_une_erreur_serveur_est_reessayee(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    c = _client([httpx.Response(503), _ok({"resultat": 42})])
    reponse = c.get("https://exemple.test/a", utiliser_cache=False)
    assert reponse.statut == 200
    assert reponse.json_ == {"resultat": 42}
    assert len(c.appels) == 2


def test_le_backoff_est_exponentiel(monkeypatch):
    pauses = []
    monkeypatch.setattr(time, "sleep", pauses.append)
    # requetes_par_seconde=0 désactive le limiteur : seules les pauses de
    # backoff sont alors enregistrées.
    c = _client([httpx.Response(500)], tentatives_max=4, requetes_par_seconde=0)
    with pytest.raises(ErreurHttp):
        c.get("https://exemple.test/a", utiliser_cache=False)
    # 1s, 2s, 4s (plus un bruit aléatoire) : chaque pause dépasse la précédente.
    assert len(pauses) == 3
    assert pauses[0] < pauses[1] < pauses[2]


def test_retry_after_est_respecte(monkeypatch):
    pauses = []
    monkeypatch.setattr(time, "sleep", pauses.append)
    c = _client([httpx.Response(429, headers={"Retry-After": "7"}), _ok()],
                requetes_par_seconde=0)
    c.get("https://exemple.test/a", utiliser_cache=False)
    assert pauses == [7.0], "le délai demandé par le serveur doit primer sur le backoff"


def test_une_erreur_client_n_est_pas_reessayee():
    """Un 404 ne s'améliorera pas en réessayant : échouer tout de suite."""
    c = _client([httpx.Response(404)])
    with pytest.raises(ErreurHttp) as info:
        c.get("https://exemple.test/a", utiliser_cache=False)
    assert info.value.statut == 404
    assert len(c.appels) == 1


def test_abandon_apres_le_nombre_maximum_de_tentatives(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    c = _client([httpx.ConnectError("réseau coupé")], tentatives_max=3)
    with pytest.raises(ErreurHttp, match="injoignable"):
        c.get("https://exemple.test/a", utiliser_cache=False)
    assert len(c.appels) == 3


# --- Cache disque ----------------------------------------------------------


def test_la_seconde_requete_identique_sort_du_cache(tmp_path):
    c = _client([_ok({"resultat": 1})], tmp_path=tmp_path)
    premiere = c.get("https://exemple.test/a", params={"q": "x"})
    seconde = c.get("https://exemple.test/a", params={"q": "x"})

    assert premiere.depuis_cache is False
    assert seconde.depuis_cache is True
    assert seconde.json_ == {"resultat": 1}
    assert len(c.appels) == 1, "la seconde requête a touché le réseau"


def test_des_parametres_differents_ne_partagent_pas_le_cache(tmp_path):
    c = _client([_ok()], tmp_path=tmp_path)
    c.get("https://exemple.test/a", params={"q": "x"})
    c.get("https://exemple.test/a", params={"q": "y"})
    assert len(c.appels) == 2


def test_un_cache_expire_est_ignore(tmp_path):
    c = _client([_ok()], tmp_path=tmp_path, cache_ttl_heures=0)
    c.get("https://exemple.test/a")
    c.get("https://exemple.test/a")
    assert len(c.appels) == 2


def test_les_erreurs_ne_sont_jamais_mises_en_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    c = _client([httpx.Response(404)], tmp_path=tmp_path)
    with pytest.raises(ErreurHttp):
        c.get("https://exemple.test/a")
    assert list(tmp_path.glob("*.json")) == []
