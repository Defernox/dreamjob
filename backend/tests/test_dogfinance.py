"""Connecteur DogFinance — sans réseau.

Deux garanties tiennent ici, et pas seulement la conversion des champs :
le connecteur n'interroge jamais la recherche filtrée que `robots.txt`
interdit, et il n'ouvre jamais plus de `PLAFOND_PAGES` pages.
"""

import json
from datetime import datetime

import pytest

from app.connectors.base import ErreurConnecteur, SearchQuery
from app.connectors.dogfinance import (
    PLAFOND_PAGES,
    URL_SITEMAP_INDEX,
    DogFinanceConnector,
)
from app.connectors.http import Reponse

from .test_france_travail import FauxHttp, FauxReglages

OFFRE = {
    "id": 480148,
    "titre": "Analyste Risques de Crédit H/F",
    "contrat": "CDI",
    "datePub": 1786781423,          # 2026-08-15 08:10:23 UTC
    "auteur": {"id": 4, "nom": "BNP Paribas"},
    "pays": {"id": 1, "nom": "France"},
    "region": {"id": 1, "nom": "Île-de-France"},
    "departement": {"id": 4, "nom": "Hauts-de-Seine", "code": "92"},
    "ville": {"id": 538, "nom": "La Défense"},
    "villeTxt": "La Défense",
    "metiers": [{"id": 118, "nom": "Analyste crédits"}],
    "missions": "<p>Vous suivez le <b>risque de contrepartie</b>.</p><ul><li>Reporting</li></ul>",
    "descEntreprise": "<p>Acteur majeur de la sc&egrave;ne financi&egrave;re.</p>",
    "urlSexy": "/offre/bnp-paribas/analyste-risques-de-credit-hf",
}

URLS_SITEMAP = [
    "https://dogfinance.com/offre/bnp-paribas/analyste-risques-de-credit-hf",
    "https://dogfinance.com/offre/sg/middle-office-produits-derives-hf",
    "https://dogfinance.com/offre/allianz/analyste-indemnisation-relation-clients-hf",
    "https://dogfinance.com/offre/manpower/boulanger-patissier-hf",
]


def _index(sitemaps=("https://cdn.example/sitemap-offers-1.xml",)):
    corps = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in sitemaps)
    return Reponse(200, None, f"<sitemapindex>{corps}</sitemapindex>", {})


def _sitemap(urls=URLS_SITEMAP):
    corps = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return Reponse(200, None, f"<urlset>{corps}</urlset>", {})


def _page(offre=OFFRE):
    bloc = json.dumps({"props": {"initialProps": {"pageProps": {"offreSSR": offre}}}})
    html = ('<html><body><script id="__NEXT_DATA__" type="application/json">'
            f'{bloc}</script></body></html>')
    return Reponse(200, None, html, {})


def _connecteur(reponses):
    return DogFinanceConnector(FauxHttp(reponses), FauxReglages())


class HttpParUrl:
    """Répond selon l'URL et non selon l'ordre d'appel.

    `FauxHttp` rejoue une séquence : au deuxième `fetch` du même connecteur, sa
    file est vide et l'index des sitemaps recevrait une page d'offre. Les tests
    de budget enchaînent justement plusieurs recherches.
    """

    def __init__(self, sitemaps, urls):
        self._index, self._sitemap = _index(sitemaps), _sitemap(urls)
        self.appels = []

    def get(self, url, **kw):
        self.appels.append({"methode": "GET", "url": url, **kw})
        if url == URL_SITEMAP_INDEX:
            return self._index
        return self._sitemap if "sitemap-offers" in url else _page()


def _requete(**kw):
    kw.setdefault("mots_cles", ["analyste risques"])
    return SearchQuery(**kw)


# ------------------------------------------------------------------ conversion

def test_conversion_d_une_offre():
    c = _connecteur([_index(), _sitemap(), _page()])
    o = c.fetch(_requete(max_offres=10))[0]
    assert o.source == "dogfinance"
    assert o.source_id == "480148"
    assert o.titre == "Analyste Risques de Crédit H/F"
    assert o.entreprise == "BNP Paribas"
    assert o.lieu == "La Défense"
    assert o.pays == "France"
    assert o.type_contrat == "CDI"
    assert o.url == "https://dogfinance.com/offre/bnp-paribas/analyste-risques-de-credit-hf"


def test_la_description_reunit_missions_et_entreprise_en_texte():
    """Le scoring cherche les compétences dans les deux champs, sans balises."""
    c = _connecteur([_index(), _sitemap(), _page()])
    description = c.fetch(_requete(max_offres=10))[0].description_brute
    assert "risque de contrepartie" in description
    assert "Acteur majeur de la scène financière" in description   # entités décodées
    assert "<" not in description and ">" not in description


def test_les_puces_restent_separees():
    """Recollées en un pavé, elles feraient perdre les limites de phrase."""
    offre = dict(OFFRE, missions="<ul><li>Bâle III</li><li>Stress tests</li></ul>")
    c = _connecteur([_index(), _sitemap(), _page(offre)])
    description = c.fetch(_requete(max_offres=10))[0].description_brute
    assert "Bâle III\nStress tests" in description


def test_la_date_de_publication_est_de_l_utc_naif():
    """La base ne stocke que de l'UTC naïf (models/base.py)."""
    c = _connecteur([_index(), _sitemap(), _page()])
    date = c.fetch(_requete(max_offres=10))[0].date_publication
    assert date == datetime(2026, 8, 15, 8, 10, 23)
    assert date.tzinfo is None


def test_le_libelle_metier_est_range_sous_la_cle_lue_par_le_scoring():
    """`metiers[].nom` joue le rôle du romeLibelle de France Travail : rangé
    ailleurs, le critère secteur ne le verrait jamais."""
    c = _connecteur([_index(), _sitemap(), _page()])
    assert c.fetch(_requete(max_offres=10))[0].raw["romeLibelle"] == "Analyste crédits"


# ----------------------------------------------------------------------- pays

def test_le_pays_est_deduit_de_l_intitule_quand_le_champ_manque():
    """Une offre sur deux n'a pas de pays renseigné."""
    offre = dict(OFFRE, pays=[], ville=[], villeTxt=None,
                 titre="VIE - Analyste Crédits - Luxembourg - H/F")
    c = _connecteur([_index(), _sitemap(), _page(offre)])
    assert c.fetch(_requete(max_offres=10))[0].pays == "Luxembourg"


def test_un_pays_introuvable_reste_vide_plutot_que_france():
    """Tout étiqueter « France » fausserait le critère pays."""
    offre = dict(OFFRE, pays=[], titre="Analyste Risques de Crédit H/F")
    c = _connecteur([_index(), _sitemap(), _page(offre)])
    assert c.fetch(_requete(max_offres=10))[0].pays == ""


def test_un_mot_ne_se_fait_pas_passer_pour_un_pays():
    """« Indemnisation » contient « Inde » : sans frontière de mot, l'offre
    serait localisée en Inde."""
    offre = dict(OFFRE, pays=[], titre="Analyste Indemnisation H/F")
    c = _connecteur([_index(), _sitemap(), _page(offre)])
    assert c.fetch(_requete(max_offres=10))[0].pays == ""


# -------------------------------------------------------------------- contrat

@pytest.mark.parametrize("brut, attendu", [
    ("CDI", "CDI"), ("CDD", "CDD"), ("STAGE", "Stage"),
    ("VIE", "V.I.E"), ("ALTERNANCE", "Alternance"), ("INTERIM", "Intérim"),
])
def test_les_contrats_rejoignent_notre_vocabulaire(brut, attendu):
    assert DogFinanceConnector._contrat({"contrat": brut}) == attendu


def test_un_contrat_absent_laisse_le_critere_non_evaluable():
    """« Autre » ferait chuter le critère à zéro pour une information manquante."""
    assert DogFinanceConnector._contrat({"contrat": ""}) == ""
    assert DogFinanceConnector._contrat({}) == ""


def test_un_contrat_connu_du_site_mais_pas_de_nous_vaut_autre():
    assert DogFinanceConnector._contrat({"contrat": "VOLONTARIAT"}) == "Autre"


# ------------------------------------------------------------ filtrage local

def test_le_filtre_exige_tous_les_mots_d_un_mot_cle():
    retenues = DogFinanceConnector._retenir(URLS_SITEMAP, _requete())
    assert retenues == [URLS_SITEMAP[0]]      # « analyste » ET « risques »


def test_le_filtre_rattrape_les_pluriels():
    """« risques » doit rencontrer « …-risque-credit »."""
    urls = ["https://dogfinance.com/offre/sg/analyste-risque-credit-hf"]
    assert DogFinanceConnector._retenir(urls, _requete()) == urls


def test_vie_survit_a_la_normalisation():
    """« V.I.E » découpé bêtement donnerait trois lettres, toutes jetées."""
    urls = ["https://dogfinance.com/offre/bnp/vie-analyste-credits-luxembourg"]
    assert DogFinanceConnector._retenir(urls, _requete(mots_cles=["V.I.E"])) == urls


def test_une_recherche_accepte_ce_qu_une_autre_rejette():
    requete = _requete(mots_cles=["analyste risques", "middle office"])
    assert DogFinanceConnector._retenir(URLS_SITEMAP, requete) == URLS_SITEMAP[:2]


# ------------------------------------------------- garanties robots.txt / droit

def test_la_recherche_filtree_interdite_n_est_jamais_appelee():
    """`robots.txt` interdit /offres?* : on ne passe que par les sitemaps."""
    http = FauxHttp([_index(), _sitemap(), _page()])
    DogFinanceConnector(http, FauxReglages()).fetch(_requete(max_offres=10))
    appels = [a["url"] for a in http.appels]
    assert appels[0] == URL_SITEMAP_INDEX
    assert not any("/offres?" in u for u in appels)


def test_le_plafond_de_pages_est_respecte():
    """Plafond juridique : jamais une partie substantielle de la base."""
    urls = [f"https://dogfinance.com/offre/x/analyste-risques-{i}" for i in range(200)]
    http = FauxHttp([_index(), _sitemap(urls), _page()])
    offres = DogFinanceConnector(http, FauxReglages()).fetch(_requete(max_offres=500))
    assert len(offres) == PLAFOND_PAGES
    assert sum(1 for a in http.appels if "/offre/" in a["url"]) == PLAFOND_PAGES


def test_le_plafond_vaut_pour_le_scan_entier_et_non_par_recherche():
    """`scan.py` construit un connecteur par source puis lui passe chaque
    recherche : quatre recherches ne doivent pas ouvrir quatre fois le plafond."""
    urls = [f"https://dogfinance.com/offre/x/analyste-risques-{i}" for i in range(200)]
    http = HttpParUrl(["https://cdn.example/sitemap-offers-1.xml"], urls)
    c = DogFinanceConnector(http, FauxReglages())
    for _ in range(4):
        c.fetch(_requete(max_offres=500))
    assert sum(1 for a in http.appels if "/offre/" in a["url"]) == PLAFOND_PAGES


def test_une_meme_annonce_n_est_pas_ouverte_deux_fois():
    """Deux recherches ramènent souvent la même URL ; la relire gâcherait le
    budget sans rien apporter."""
    urls = ["https://dogfinance.com/offre/sg/analyste-risques-middle-office-hf"]
    http = HttpParUrl(["https://cdn.example/sitemap-offers-1.xml"], urls)
    c = DogFinanceConnector(http, FauxReglages())
    c.fetch(_requete(mots_cles=["analyste risques"]))
    c.fetch(_requete(mots_cles=["middle office"]))
    assert sum(1 for a in http.appels if "/offre/" in a["url"]) == 1


def test_max_offres_abaisse_le_plafond_mais_ne_le_leve_pas():
    urls = [f"https://dogfinance.com/offre/x/analyste-risques-{i}" for i in range(200)]
    http = FauxHttp([_index(), _sitemap(urls), _page()])
    offres = DogFinanceConnector(http, FauxReglages()).fetch(_requete(max_offres=5))
    assert len(offres) == 5


def test_tous_les_sitemaps_d_offres_sont_suivis():
    """Un quatrième sitemap doit être pris sans toucher au code."""
    http = FauxHttp([
        _index(["https://cdn.example/sitemap-offers-1.xml",
                "https://cdn.example/sitemap-offers-2.xml"]),
        _sitemap(), _page(),
    ])
    DogFinanceConnector(http, FauxReglages()).fetch(_requete(max_offres=10))
    assert sum(1 for a in http.appels if "sitemap-offers" in a["url"]) == 2


# ------------------------------------------------------------------- pannes

def test_un_index_sans_sitemap_d_offres_est_une_panne():
    c = _connecteur([_index(["https://cdn.example/sitemap-articles-1.xml"])])
    with pytest.raises(ErreurConnecteur, match="sitemap-offers"):
        c.fetch(_requete(max_offres=10))


def test_des_pages_toutes_illisibles_sont_une_panne_et_non_zero_offre():
    """Sinon un changement de structure passerait pour un marché sans offres."""
    vide = Reponse(200, None, "<html><body>rien</body></html>", {})
    c = _connecteur([_index(), _sitemap(), vide])
    with pytest.raises(ErreurConnecteur, match="structure du site"):
        c.fetch(_requete(max_offres=10))


def test_une_page_illisible_isolee_ne_perd_pas_les_autres():
    vide = Reponse(200, None, "<html><body>rien</body></html>", {})
    requete = _requete(mots_cles=["analyste risques", "middle office"])
    c = _connecteur([_index(), _sitemap(), vide, _page()])
    assert len(c.fetch(requete)) == 1
