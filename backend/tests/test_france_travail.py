"""Connecteur France Travail — sans réseau : un faux client HTTP rejoue des
réponses de la forme exacte de l'API.

Ce qui est vérifié : l'authentification, la pagination, les codes de retour
inhabituels (204), la traduction des types de contrat, et surtout que les
erreurs sortent en français exploitable.
"""

import json

import pytest

from app.connectors.base import ConnecteurNonConfigure, ErreurConnecteur, SearchQuery
from app.connectors.france_travail import URL_RECHERCHE, URL_TOKEN, FranceTravailConnector
from app.connectors.http import ErreurHttp, Reponse

from .conftest import FIXTURES

REPONSE = json.loads((FIXTURES / "france_travail_reponse.json").read_text(encoding="utf-8"))


class FauxReglages:
    """Juste ce que le connecteur lit : les secrets."""

    def __init__(self, **secrets):
        self._secrets = secrets

    def secret(self, nom):
        return self._secrets.get(nom)


class FauxHttp:
    """Rejoue des réponses et enregistre les appels.

    La dernière réponse est répétée si la liste s'épuise : un connecteur qui
    interroge plusieurs pays ferait sinon échouer le test sur un détail de
    plomberie plutôt que sur ce qu'il vérifie.
    """

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels = []

    def _suivante(self, methode, url, **kw):
        self.appels.append({"methode": methode, "url": url, **kw})
        suite = self.reponses.pop(0) if len(self.reponses) > 1 else self.reponses[0]
        if isinstance(suite, Exception):
            raise suite
        return suite

    def get(self, url, **kw):
        return self._suivante("GET", url, **kw)

    def post(self, url, **kw):
        return self._suivante("POST", url, **kw)

    def requete(self, methode, url, **kw):
        return self._suivante(methode, url, **kw)


def _jeton(expire_dans=1499):
    return Reponse(200, {"access_token": "jeton-test", "expires_in": expire_dans}, "", {})


def _page(resultats, statut=200):
    return Reponse(statut, {"resultats": resultats}, "", {})


CONFIGURE = dict(FRANCE_TRAVAIL_CLIENT_ID="id", FRANCE_TRAVAIL_CLIENT_SECRET="secret")


def _connecteur(reponses, **secrets):
    return FranceTravailConnector(FauxHttp(reponses), FauxReglages(**(secrets or CONFIGURE)))


# --- Configuration ---------------------------------------------------------


def test_sans_identifiants_le_connecteur_le_dit_clairement():
    c = FranceTravailConnector(FauxHttp([]), FauxReglages())
    with pytest.raises(ConnecteurNonConfigure) as info:
        c.fetch(SearchQuery())
    assert "FRANCE_TRAVAIL_CLIENT_ID" in str(info.value)
    assert "francetravail.io" in str(info.value)


# --- Authentification ------------------------------------------------------


def test_le_jeton_n_est_demande_qu_une_fois():
    c = _connecteur([_jeton(), _page(REPONSE["resultats"])])
    c.fetch(SearchQuery(max_offres=10))
    c.http.reponses = [_page(REPONSE["resultats"])]      # plus de réponse token disponible
    c.fetch(SearchQuery(max_offres=10))
    assert sum(1 for a in c.http.appels if a["url"] == URL_TOKEN) == 1


def test_le_jeton_n_est_jamais_mis_en_cache_disque():
    c = _connecteur([_jeton(), _page([])])
    c.fetch(SearchQuery(max_offres=10))
    appel_token = next(a for a in c.http.appels if a["url"] == URL_TOKEN)
    assert appel_token["utiliser_cache"] is False


def test_identifiants_refuses_donnent_un_message_actionnable():
    c = _connecteur([ErreurHttp(401, "invalid_client")])
    with pytest.raises(ErreurConnecteur) as info:
        c.fetch(SearchQuery())
    message = str(info.value)
    assert "identifiants" in message.lower()
    assert "Offres d'emploi v2" in message


def test_panne_serveur_ne_se_deguise_pas_en_probleme_d_identifiants():
    c = _connecteur([ErreurHttp(503, "service unavailable")])
    with pytest.raises(ErreurConnecteur) as info:
        c.fetch(SearchQuery())
    assert "identifiants" not in str(info.value).lower()


# --- Conversion des offres -------------------------------------------------


def test_conversion_d_une_offre_complete():
    c = _connecteur([_jeton(), _page(REPONSE["resultats"])])
    offres = c.fetch(SearchQuery(max_offres=10))
    analyste = offres[0]

    assert analyste.source == "france_travail"
    assert analyste.source_id == "195XKQL"
    assert analyste.titre == "Analyste risques de crédit (H/F)"
    assert analyste.entreprise == "BANQUE EXEMPLE"
    assert analyste.lieu == "75 - PARIS 09"
    assert analyste.pays == "France"
    assert analyste.type_contrat == "CDI"
    assert "solvabilité" in analyste.description_brute
    # La charge utile d'origine est archivée : l'annonce peut disparaître.
    assert analyste.raw["romeCode"] == "C1206"


def test_la_date_est_convertie_en_utc_naif():
    """Convention de la base : pas de fuseau en SQLite (cf. CLAUDE.md)."""
    c = _connecteur([_jeton(), _page(REPONSE["resultats"])])
    date = c.fetch(SearchQuery(max_offres=10))[0].date_publication
    assert date.tzinfo is None
    assert (date.year, date.month, date.day, date.hour) == (2026, 8, 27, 9)


def test_l_alternance_est_reconnue_malgre_un_typeContrat_CDD():
    """Le champ typeContrat dit « CDD » : seul natureContrat révèle l'alternance."""
    c = _connecteur([_jeton(), _page(REPONSE["resultats"])])
    alternance = c.fetch(SearchQuery(max_offres=10))[1]
    assert alternance.type_contrat == "Alternance"


def test_mission_interim_traduite():
    c = _connecteur([_jeton(), _page(REPONSE["resultats"])])
    assert c.fetch(SearchQuery(max_offres=10))[2].type_contrat == "Intérim"


def test_url_reconstruite_quand_la_source_n_en_donne_pas():
    c = _connecteur([_jeton(), _page(REPONSE["resultats"])])
    offres = c.fetch(SearchQuery(max_offres=10))
    assert offres[1].url.endswith("/195XKQM")            # reconstruite
    assert offres[2].url == "https://partenaire.example/offre/42"   # fournie


def test_offre_sans_entreprise_ne_casse_rien():
    c = _connecteur([_jeton(), _page(REPONSE["resultats"])])
    assert c.fetch(SearchQuery(max_offres=10))[2].entreprise == ""


# --- Pagination et codes de retour -----------------------------------------


def test_aucun_resultat_204_renvoie_une_liste_vide():
    c = _connecteur([_jeton(), Reponse(204, None, "", {})])
    assert c.fetch(SearchQuery(max_offres=150)) == []


def test_pagination_sur_plusieurs_pages():
    pleine = [{"id": f"O{i}", "intitule": f"Offre {i}"} for i in range(150)]
    c = _connecteur([_jeton(), _page(pleine, statut=206), _page(pleine[:20], statut=206)])
    offres = c.fetch(SearchQuery(max_offres=300))
    assert len(offres) == 170
    plages = [a["params"]["range"] for a in c.http.appels if a["url"] == URL_RECHERCHE]
    assert plages == ["0-149", "150-299"]


def test_une_page_incomplete_arrete_la_pagination():
    c = _connecteur([_jeton(), _page(REPONSE["resultats"], statut=206)])
    c.fetch(SearchQuery(max_offres=3000))
    assert len([a for a in c.http.appels if a["url"] == URL_RECHERCHE]) == 1


def test_max_offres_est_respecte():
    c = _connecteur([_jeton(), _page(REPONSE["resultats"])])
    c.fetch(SearchQuery(max_offres=50))
    plage = next(a["params"]["range"] for a in c.http.appels if a["url"] == URL_RECHERCHE)
    assert plage == "0-49"


# --- Paramètres de recherche -----------------------------------------------


def test_les_filtres_sont_transmis_a_l_api():
    c = _connecteur([_jeton(), _page([])])
    c.fetch(SearchQuery(mots_cles=["analyste", "risques"], departement="75",
                        publiee_depuis_jours=5, contrats=["CDI"], max_offres=10))
    params = next(a["params"] for a in c.http.appels if a["url"] == URL_RECHERCHE)
    assert params["motsCles"] == "analyste,risques"
    assert params["departement"] == "75"
    assert params["publieeDepuis"] == "7"      # l'API n'accepte que 1/3/7/14/31
    assert params["typeContrat"] == "CDI"


def test_plusieurs_contrats_ne_sont_pas_envoyes_a_l_api():
    """L'API n'en accepte qu'un : on récupère tout et on filtre ensuite."""
    c = _connecteur([_jeton(), _page([])])
    c.fetch(SearchQuery(contrats=["CDI", "CDD"], max_offres=10))
    params = next(a["params"] for a in c.http.appels if a["url"] == URL_RECHERCHE)
    assert "typeContrat" not in params


@pytest.mark.parametrize("demande, attendu", [
    (1, "1"), (2, "3"), (5, "7"), (7, "7"), (10, "14"), (30, "31"), (90, "31"),
])
def test_l_anciennete_est_arrondie_vers_le_haut(demande, attendu):
    """Arrondir vers le bas ferait silencieusement disparaître des offres."""
    c = _connecteur([_jeton(), _page([])])
    c.fetch(SearchQuery(publiee_depuis_jours=demande, max_offres=10))
    params = next(a["params"] for a in c.http.appels if a["url"] == URL_RECHERCHE)
    assert params["publieeDepuis"] == attendu


# --- Pays ------------------------------------------------------------------


@pytest.mark.parametrize("lieu, attendu", [
    ({"libelle": "75 - Paris 09", "codePostal": "75009"}, "France"),
    ({"libelle": "2A - Ajaccio"}, "France"),          # Corse : 2A/2B, pas un nombre
    ({"libelle": "974 - Saint-Denis"}, "France"),     # outre-mer : 3 chiffres
    ({"libelle": "Luxembourg"}, "Luxembourg"),
    ({"libelle": "Bruxelles, Belgique"}, "Belgique"),
    ({"libelle": "Dublin, Irlande"}, "Irlande"),
    ({}, "France"),                                    # lieu absent : l'API est française
    ({"libelle": "Quelque part"}, ""),                 # inconnu : on n'affirme rien
])
def test_le_pays_ne_vaut_pas_toujours_france(lieu, attendu):
    """Étiqueter une offre luxembourgeoise « France » fausserait le critère pays."""
    assert FranceTravailConnector._pays({"lieuTravail": lieu}) == attendu


def test_une_offre_a_l_etranger_conserve_son_pays():
    brute = {"id": "X", "intitule": "Depositary Bank Agent",
             "lieuTravail": {"libelle": "Luxembourg"}}
    c = _connecteur([_jeton(), _page([brute])])
    assert c.fetch(SearchQuery(max_offres=10))[0].pays == "Luxembourg"
