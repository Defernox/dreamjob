"""Les sites carrières des employeurs — sans réseau.

Ce que ces tests protègent :

- **la politesse** : robots.txt lu avant toute page, et respecté ; une fiche
  n'est ouverte que pour une offre nouvelle qui répond à une recherche ;
- **le tri** : un intitulé anglais répond à une recherche française ;
- **la fenêtre** : la liste s'arrête à la première offre trop ancienne ;
- **l'isolement des pannes** : un employeur en panne n'arrête pas les autres.
"""

from datetime import timedelta

import pytest
import yaml

from app.config import reglages
from app.connectors.base import ErreurConnecteur, SearchQuery
from app.connectors.employeurs import EmployeursConnector
from app.connectors.employeurs.commun import cles, contrat, correspond, texte
from app.connectors.employeurs.pays import depuis_iso, depuis_lieu, depuis_nom
from app.connectors.employeurs.workday import adresses, jours
from app.connectors.employeurs.registre import Employeur
from app.connectors.http import ErreurHttp, Reponse
from app.models.base import maintenant

ROBOTS_WORKDAY = "User-agent: *\nAllow: /Global/\nDisallow: /refreshFacet/\n"
PAYS = {"GB": ("United Kingdom", "id-gb"), "FR": ("France", "id-fr"), "IN": ("India", "id-in")}


def _offre(titre, jours_=0, iso="GB", lieu="London, England"):
    return {"title": titre, "jours": jours_, "iso": iso, "lieu": lieu}


class SiteWorkday:
    """Un locataire Workday : liste triée du plus récent au plus ancien, filtre
    par pays, fiches, robots.txt. Répond selon l'URL, depuis plusieurs fils."""

    def __init__(self, offres, robots=ROBOTS_WORKDAY, statut_robots=200, en_panne=False):
        self.offres = sorted(offres, key=lambda o: o["jours"])
        self.robots, self.statut_robots, self.en_panne = robots, statut_robots, en_panne
        self.appels = []

    @staticmethod
    def _chemin(o):
        return f"/job/{o['lieu'].split(',')[0]}/{o['title'].replace(' ', '-')}_R-{abs(hash(o['title'])) % 10**6}"

    def get(self, url, **kw):
        self.appels.append(("GET", url, None))
        if url.endswith("/robots.txt"):
            return Reponse(self.statut_robots, None, self.robots, {})
        for o in self.offres:
            if url.endswith(self._chemin(o)):
                return Reponse(200, {"jobPostingInfo": {
                    "title": o["title"], "jobDescription": "<p>Analyse des <b>risques</b>.</p><ul><li>Bâle III</li></ul>",
                    "location": o["lieu"], "startDate": (maintenant() - timedelta(days=o["jours"])).date().isoformat(),
                    "timeType": "Full time", "externalUrl": f"https://publique{self._chemin(o)}",
                    "jobRequisitionLocation": {"country": {"descriptor": PAYS[o["iso"]][0], "alpha2Code": o["iso"]}},
                }}, "", {})
        return Reponse(404, None, "", {})

    def post(self, url, corps_json=None, **kw):
        self.appels.append(("POST", url, corps_json))
        if self.en_panne:
            raise ErreurHttp(503, "en panne")
        voulus = {i for ids in corps_json["appliedFacets"].values() for i in ids}
        # Une offre sur plusieurs sites est listée dès que L'UN d'eux passe le
        # filtre (`facette`) ; sa fiche ne donne que le lieu principal (`iso`).
        retenues = [o for o in self.offres if not voulus or PAYS[o.get("facette", o["iso"])][1] in voulus]
        page = retenues[corps_json["offset"]:corps_json["offset"] + corps_json["limit"]]
        libelle = {0: "Posted Today", 1: "Posted Yesterday"}
        return Reponse(200, {
            "total": len(retenues) if corps_json["offset"] == 0 else 0,
            "jobPostings": [{
                "title": o["title"], "externalPath": self._chemin(o), "locationsText": o["lieu"],
                "postedOn": libelle.get(o["jours"], f"Posted {o['jours']} Days Ago" if o["jours"] < 30
                                        else "Posted 30+ Days Ago"),
            } for o in page],
            "facets": [{"facetParameter": "locationMainGroup", "values": [
                {"facetParameter": "Location_Country",
                 "values": [{"descriptor": d, "id": i, "count": 1} for d, i in PAYS.values()]}]}],
        }, "", {})


class Sites:
    """Plusieurs employeurs derrière un seul client : l'hôte choisit le site."""

    def __init__(self, **sites):
        self.sites = sites

    def _site(self, url):
        return next(s for hote, s in self.sites.items() if f"//{hote}." in url)

    def get(self, url, **kw):
        return self._site(url).get(url, **kw)

    def post(self, url, **kw):
        return self._site(url).post(url, **kw)


@pytest.fixture
def registre(tmp_path):
    def ecrire(*employeurs):
        chemin = tmp_path / "employeurs.yaml"
        chemin.write_text(yaml.safe_dump({"employeurs": {"banques": list(employeurs)}},
                                         allow_unicode=True), encoding="utf-8")
        r = reglages().model_copy(deep=True)
        r.employeurs.fichier = str(chemin)
        return r
    return ecrire


def _employeur(hote, nom=None, **kw):
    return {"nom": nom or hote.title(), "logiciel": "workday",
            "adresse": f"https://{hote}.wd1.myworkdayjobs.com/en-US/Global", **kw}


def _requete(*mots, pays=("France", "Royaume-Uni"), **kw):
    return SearchQuery(mots_cles=list(mots) or ["analyste risques"], pays=list(pays), **kw)


# --- Le tri des intitulés -------------------------------------------------------------


def test_un_intitule_anglais_repond_a_une_recherche_francaise():
    assert correspond("Risk Analyst", cles(_requete("analyste risques")))
    assert correspond("Analyst, Market Risk", cles(_requete("analyste risques")))
    assert not correspond("Software Engineer", cles(_requete("analyste risques")))


def test_au_dela_de_deux_mots_un_seul_peut_manquer():
    recherche = cles(_requete("Analyste risques de crédit"))
    assert correspond("Credit Risk Officer", recherche)
    assert not correspond("Credit Officer", recherche)


def test_une_recherche_sans_mot_cle_ne_demande_rien():
    assert cles(SearchQuery(mots_cles=[])) == []


def test_le_contrat_se_lit_dans_l_intitule_sans_rien_supposer():
    assert contrat("Stage Assistant(e) Gestion Obligataire") == "Stage"
    assert contrat("Fund Finance Intern - November 2026") == "Stage"
    assert contrat("(12 month FTC) Investment Group Assistant") == "CDD"
    assert contrat("V.I.E - Analyste crédit") == "V.I.E"
    assert contrat("Analyste Middle Office") == ""


def test_le_html_devient_du_texte_avec_ses_puces():
    assert texte("<p>Analyse</p><ul><li>Bâle&nbsp;III</li><li>IFRS 9</li></ul>") == "Analyse\n\n- Bâle III\n\n- IFRS 9"


# --- Les pays ----------------------------------------------------------------------------


@pytest.mark.parametrize("lieu, pays", [
    ("London, England", "Royaume-Uni"),
    ("Paris-La Défense", "France"),
    ("Hong Kong SAR, China", "Hong Kong"),
    ("Zurich", "Suisse"),
    ("3 Locations", ""),
    ("Nulle part", ""),
])
def test_le_pays_d_un_lieu(lieu, pays):
    assert depuis_lieu(lieu) == pays


def test_les_codes_et_les_noms_de_pays():
    assert depuis_iso("gb") == "Royaume-Uni"
    assert depuis_nom("Deutschland") == "Allemagne"
    assert depuis_nom("United States of America") == "États-Unis"
    assert depuis_iso("ZZ") == depuis_nom("Atlantide") == ""


# --- Workday ------------------------------------------------------------------------------


def test_l_adresse_d_un_site_workday():
    e = Employeur(nom="X", adresse="https://statestreet.wd1.myworkdayjobs.com/en-US/Global/")
    assert adresses(e) == ("https://statestreet.wd1.myworkdayjobs.com/wday/cxs/statestreet/Global",
                           "https://statestreet.wd1.myworkdayjobs.com/Global")


@pytest.mark.parametrize("texte_, attendu", [
    ("Posted Today", 0), ("Posted Yesterday", 1), ("Posted 3 Days Ago", 3),
    ("Posted 30+ Days Ago", 31), ("Publié récemment", None),
])
def test_la_date_relative_de_workday(texte_, attendu):
    assert jours(texte_) == attendu


def test_seuls_les_pays_voulus_sont_demandes(registre):
    site = SiteWorkday([_offre("Risk Analyst")])
    c = EmployeursConnector(Sites(banque=site), registre(_employeur("banque")))
    c.fetch(_requete())
    filtres = [corps["appliedFacets"] for m, _, corps in site.appels if m == "POST" and corps["limit"] > 1]
    assert filtres == [{"Location_Country": ["id-gb", "id-fr"]}]


def test_la_liste_s_arrete_a_la_premiere_offre_trop_ancienne(registre):
    offres = [_offre(f"Risk Analyst {i}", jours_=i) for i in range(60)]
    site = SiteWorkday(offres)
    c = EmployeursConnector(Sites(banque=site), registre(_employeur("banque")))
    trouvees = c.fetch(_requete(publiee_depuis_jours=1))
    assert sorted(o.titre for o in trouvees) == ["Risk Analyst 0", "Risk Analyst 1"]
    pages = [corps for m, _, corps in site.appels if m == "POST" and corps["limit"] > 1]
    assert len(pages) == 1, "la première page suffisait"


def test_une_fiche_n_est_ouverte_que_pour_une_offre_nouvelle_qui_repond(registre):
    site = SiteWorkday([_offre("Risk Analyst"), _offre("Software Engineer"), _offre("Credit Risk Analyst")])
    c = EmployeursConnector(Sites(banque=site), registre(_employeur("banque", nom="Banque")))
    connue = [o for o in c.fetch(_requete()) if o.titre == "Credit Risk Analyst"][0].source_id

    site.appels.clear()
    c2 = EmployeursConnector(Sites(banque=site), registre(_employeur("banque", nom="Banque")))
    c2.connus = {connue}
    trouvees = {o.titre: o for o in c2.fetch(_requete())}
    fiches = [url for m, url, _ in site.appels if m == "GET" and "/job/" in url]
    assert len(fiches) == 1 and "Risk-Analyst_" in fiches[0] and "Credit" not in fiches[0]
    assert set(trouvees) == {"Risk Analyst", "Credit Risk Analyst"}
    # La connue est seulement signalée en ligne : pas de description à refaire.
    assert trouvees["Credit Risk Analyst"].description_brute == ""


def test_une_offre_complete(registre):
    site = SiteWorkday([_offre("Stage Analyste Risques", iso="FR", lieu="Paris, France", jours_=2)])
    c = EmployeursConnector(Sites(banque=site), registre(_employeur("banque", nom="Banque Test")))
    o = c.fetch(_requete())[0]
    assert o.source == "employeurs"
    assert o.source_id.startswith("banque-test:")
    assert o.entreprise == "Banque Test"
    assert o.pays == "France"
    assert o.type_contrat == "Stage"
    assert o.description_brute == "Analyse des risques.\n\n- Bâle III"
    assert o.date_publication.date() == (maintenant() - timedelta(days=2)).date()
    assert o.url.startswith("https://publique/job/")


def test_la_liste_est_lue_une_fois_par_scan(registre):
    site = SiteWorkday([_offre("Risk Analyst"), _offre("Middle Office Analyst")])
    c = EmployeursConnector(Sites(banque=site), registre(_employeur("banque")))
    c.fetch(_requete("analyste risques"))
    c.fetch(_requete("middle office"))
    listes = [corps for m, _, corps in site.appels if m == "POST" and corps["limit"] > 1]
    assert len(listes) == 1


def test_une_recherche_v_i_e_ne_veut_que_des_v_i_e_ecrits(registre):
    """Un contrat que l'annonce ne précise pas est un CDI ou un CDD : le laisser
    passer versait tous les postes « finance » dans la recherche V.I.E."""
    site = SiteWorkday([_offre("Financial Advisor"), _offre("V.I.E - Finance Analyst")])
    c = EmployeursConnector(Sites(banque=site), registre(_employeur("banque")))
    assert [o.titre for o in c.fetch(_requete("finance", contrats=["V.I.E"]))] == ["V.I.E - Finance Analyst"]
    assert len(c.fetch(_requete("finance", contrats=["CDI", "V.I.E"]))) == 2


def test_le_pays_de_la_fiche_a_le_dernier_mot(registre):
    """« 3 Locations » en liste ne dit rien ; la fiche dit Inde."""
    site = SiteWorkday([{**_offre("Risk Analyst", iso="IN", lieu="3 Locations"), "facette": "FR"}])
    c = EmployeursConnector(Sites(banque=site), registre(_employeur("banque")))
    assert c.fetch(_requete(pays=("France",))) == []
    assert [m for m, url, _ in site.appels if "/job/" in url], "la fiche a bien été lue"


def test_le_plafond_garde_les_plus_recentes(registre):
    site = SiteWorkday([_offre(f"Risk Analyst {i}", jours_=i) for i in range(5)])
    c = EmployeursConnector(Sites(banque=site), registre(_employeur("banque")))
    assert sorted(o.titre for o in c.fetch(_requete(max_offres=2))) == ["Risk Analyst 0", "Risk Analyst 1"]


# --- La politesse, les pannes ---------------------------------------------------------------


def test_robots_txt_qui_interdit_n_est_pas_franchi(registre):
    site = SiteWorkday([_offre("Risk Analyst")], robots="User-agent: *\nDisallow: /\n")
    c = EmployeursConnector(Sites(banque=site), registre(_employeur("banque")))
    with pytest.raises(ErreurConnecteur):
        c.fetch(_requete())
    assert [m for m, *_ in site.appels] == ["GET"], "seul robots.txt a été lu"
    assert "robots.txt" in c.pannes["Banque"]


def test_un_robots_txt_refuse_a_tous_n_interdit_rien(registre):
    """RFC 9309 : un 4xx n'interdit rien. Oracle renvoie 403 à tout le monde."""
    site = SiteWorkday([_offre("Risk Analyst")], robots="", statut_robots=403)
    c = EmployeursConnector(Sites(banque=site), registre(_employeur("banque")))
    assert len(c.fetch(_requete())) == 1


def test_un_robots_txt_en_panne_fait_s_abstenir(registre):
    site = SiteWorkday([_offre("Risk Analyst")], robots="", statut_robots=503)
    c = EmployeursConnector(Sites(banque=site), registre(_employeur("banque")))
    with pytest.raises(ErreurConnecteur):
        c.fetch(_requete())
    assert not [m for m, *_ in site.appels if m == "POST"]


def test_un_employeur_en_panne_n_arrete_pas_les_autres(registre):
    sites = Sites(panne=SiteWorkday([], en_panne=True), banque=SiteWorkday([_offre("Risk Analyst")]))
    c = EmployeursConnector(sites, registre(_employeur("panne"), _employeur("banque")))
    assert [o.entreprise for o in c.fetch(_requete())] == ["Banque"]
    assert list(c.pannes) == ["Panne"]


def test_un_employeur_refuse_ou_a_venir_n_est_jamais_interroge(registre):
    site = SiteWorkday([_offre("Risk Analyst")])
    c = EmployeursConnector(Sites(banque=site), registre(
        _employeur("banque", statut="refuse", motif="protection anti-robot")))
    assert c.fetch(_requete()) == []
    assert site.appels == []
