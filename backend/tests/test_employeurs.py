"""Les sites carrières des employeurs — sans réseau.

Ce que ces tests protègent :

- **la politesse** : robots.txt lu avant toute page, et respecté ; une fiche
  n'est ouverte que pour une offre nouvelle qui répond à une recherche ;
- **le tri** : un intitulé anglais répond à une recherche française ;
- **la fenêtre** : la liste s'arrête à la première offre trop ancienne ;
- **l'isolement des pannes** : un employeur en panne n'arrête pas les autres.
"""

import json
from datetime import datetime, timedelta

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

    def ralentir(self, hote, secondes):
        site = self._site(f"https://{hote}/")
        if hasattr(site, "ralentir"):
            site.ralentir(hote, secondes)


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


# --- Talentsoft ----------------------------------------------------------------------------


class SiteTalentsoft:
    """Un site Talentsoft : flux RSS (les plus récentes, datées), liste HTML
    paginée (cartes ou liste, sans date), fiches en champs `fld…`."""

    def __init__(self, offres, gabarit="card", par_page=2, hote="banque"):
        self.offres, self.gabarit, self.par_page, self.hote = offres, gabarit, par_page, hote
        self.appels = []

    def get(self, url, **kw):
        self.appels.append(("GET", url, None))
        if url.endswith("/robots.txt"):
            return Reponse(200, None, "", {})
        if "offerRss.ashx" in url:
            items = "".join(
                f"<item><link>https://{self.hote}.talent-soft.com/Pages/Offre/detailoffre.aspx?idOffre={o['id']}&amp;LCID=1036</link>"
                f"<category>Métiers</category><category>{o['contrat']}</category><category>{o['ville']}</category>"
                f"<title>2026-{o['id']} - {o['titre']}</title>"
                f"<pubDate>{(maintenant() - timedelta(days=o['jours'])).strftime('%a, %d %b %Y %H:%M:%S')} Z</pubDate></item>"
                for o in self.offres[:20])
            return Reponse(200, None, f'<?xml version="1.0" encoding="utf-8"?><rss><channel>{items}</channel></rss>', {})
        if "liste-offres.aspx" in url:
            page = int(url.split("page=")[1].split("&")[0])
            tranche = self.offres[(page - 1) * self.par_page: page * self.par_page]
            lien = "ts-offer-card__title-link" if self.gabarit == "card" else "ts-offer-list-item__title-link"
            liste = "ts-offer-card-content__list" if self.gabarit == "card" else "ts-offer-list-item__description"
            html = "".join(
                f'<h3><a class="{lien} " href="/offre-de-emploi/emploi-x_{o["id"]}.aspx" title="2026-{o["id"]}">'
                f' {o["titre"]} </a></h3><ul class="{liste} "><li>{o["contrat"]}</li>'
                + (f"<li>{o['pays']}</li>" if o.get("pays") else "") + f'<li class="noBorder">{o["ville"]}</li></ul>'
                for o in tranche)
            return Reponse(200, None, f"<html>{html}</html>", {})
        o = next(o for o in self.offres if f"_{o['id']}.aspx" in url or f"idOffre={o['id']}" in url)
        zones = f"Europe, {o['pays']}, Ile-de-France" if o.get("pays") else ""
        return Reponse(200, None, (
            '<div id="contenu-ficheoffre"><h2 class="JobDescription">Description du poste</h2>'
            f'<p id="fldjobdescription_jobtitle">{o["titre"]}</p>'
            f'<p id="fldjobdescription_contract">{o["contrat"]}</p>'
            '<div id="fldjobdescription_description1"><p>Analyse du <strong>risque de crédit</strong>.</p></div>'
            f'<p id="fldlocation_location_geographicalareacollection">{zones}</p>'
            f'<p id="fldlocation_joblocation">{o["ville"]}</p></div><a>Postuler</a>'), {})


def _ts(ident, titre, jours_=0, contrat_="CDI", pays="France", ville="Montrouge"):
    return {"id": ident, "titre": titre, "jours": jours_, "contrat": contrat_, "pays": pays, "ville": ville}


def _employeur_ts(hote, **kw):
    return {"nom": hote.title(), "logiciel": "talentsoft", "adresse": f"https://{hote}.talent-soft.com", **kw}


def test_talentsoft_la_veille_ne_lit_que_le_flux(registre):
    site = SiteTalentsoft([_ts(2, "Analyste risques de crédit H/F"), _ts(1, "Analyste risques ALM", jours_=5)])
    c = EmployeursConnector(Sites(banque=site), registre(_employeur_ts("banque")))
    trouvees = c.fetch(_requete(publiee_depuis_jours=1))
    assert [o.titre for o in trouvees] == ["Analyste risques de crédit H/F"]
    assert not [url for _, url, _ in site.appels if "liste-offres" in url], "le flux suffisait"


@pytest.mark.parametrize("gabarit", ["card", "list-item"])
def test_talentsoft_le_scan_parcourt_la_liste(registre, gabarit):
    offres = [_ts(i, f"Analyste risques {i}", jours_=i) for i in range(5, 0, -1)]
    site = SiteTalentsoft(offres, gabarit=gabarit)
    c = EmployeursConnector(Sites(banque=site), registre(_employeur_ts("banque")))
    trouvees = c.fetch(_requete())
    assert sorted(o.titre for o in trouvees) == [f"Analyste risques {i}" for i in range(1, 6)]
    pages = [url for _, url, _ in site.appels if "liste-offres" in url]
    assert len(pages) == 4, "trois pages pleines, puis une vide qui arrête"


def test_talentsoft_une_fiche_complete(registre):
    site = SiteTalentsoft([_ts(7, "Stage - Analyste risques", contrat_="Stage", jours_=2)])
    c = EmployeursConnector(Sites(banque=site), registre(_employeur_ts("banque")))
    o = c.fetch(_requete())[0]
    assert (o.source_id, o.pays, o.type_contrat, o.lieu) == ("banque:7", "France", "Stage", "Montrouge")
    assert "Analyse du risque de crédit." in o.description_brute
    assert o.date_publication.date() == (maintenant() - timedelta(days=2)).date()


def test_un_pays_par_defaut_quand_la_fiche_ne_dit_que_la_ville(registre):
    """Arkéa ne donne que « Brest »."""
    site = SiteTalentsoft([_ts(3, "Analyste risques", pays="", ville="Brest")])
    c = EmployeursConnector(Sites(banque=site), registre(_employeur_ts("banque", pays_par_defaut="France")))
    assert [o.pays for o in c.fetch(_requete())] == ["France"]


# --- SuccessFactors ----------------------------------------------------------------------------


class SiteSuccessFactors:
    """Un site SuccessFactors : recherche triée par date et paginée par
    `startrow`, en tableau (avec date) ou en tuiles (sans), fiches en
    microdonnées. `/services/` est interdit, comme sur les vrais sites."""

    def __init__(self, offres, gabarit="tableau", par_page=2):
        self.offres = sorted(offres, key=lambda o: o["jours"])
        self.gabarit, self.par_page = gabarit, par_page
        self.appels = []

    def get(self, url, **kw):
        self.appels.append(("GET", url, None))
        if url.endswith("/robots.txt"):
            return Reponse(200, None, "User-agent: *\nDisallow: /services/\n", {})
        if "/search/" in url:
            debut = int(url.split("startrow=")[1])
            tranche = self.offres[debut:debut + self.par_page]
            if self.gabarit == "tableau":
                lignes = "".join(
                    f'<tr class="data-row"><td><a href="/job/Paris-X/{o["id"]}/" class="jobTitle-link">{o["titre"]}</a>'
                    f'<span class="jobLocation"> Paris, FR <small>+1 more</small></span>'
                    f'<span class="jobDate">{(maintenant() - timedelta(days=o["jours"])).strftime("%d %b %Y")} </span></td></tr>'
                    for o in tranche)
            else:
                lignes = "".join(
                    f'<li class="job-tile"><a class="jobTitle-link" href="/job/Paris-X/{o["id"]}/">{o["titre"]}</a>'
                    f'<div id="job-{o["id"]}-desktop-section-location-value">Paris, 75, FR</div></li>'
                    for o in tranche)
            return Reponse(200, None, f"<html>{lignes}</html>", {})
        o = next(o for o in self.offres if f"/{o['id']}/" in url)
        publiee = (maintenant() - timedelta(days=o["jours"])).strftime("%a %b %d 02:00:00 UTC %Y")
        return Reponse(200, None, (
            f'<meta itemprop="addressLocality" content="Paris"><meta itemprop="addressCountry" content="FR">'
            f'<meta itemprop="datePosted" content="{publiee}">'
            '<span itemprop="description"><span class="jobdescription"><p>Suivi du <b>risque</b> de marché.</p>'
            '</span></span><div class="applylink">Postuler</div>'), {})


def _sf(ident, titre, jours_=0):
    return {"id": ident, "titre": titre, "jours": jours_}


def _employeur_sf(hote):
    return {"nom": hote.title(), "logiciel": "successfactors", "adresse": f"https://{hote}.example.com"}


@pytest.mark.parametrize("affichee, attendue", [
    ("28 Sept 2026", (2026, 9, 28)), ("Sep 28, 2026", (2026, 9, 28)), ("28 sept. 2026", (2026, 9, 28)),
    ("28/09/2026", (2026, 9, 28)), ("28.09.2026", (2026, 9, 28)), ("12 Mär 2026", (2026, 3, 12)),
    # « mardi » commence comme « mars ».
    ("mardi 29 sept. 2026", (2026, 9, 29)),
])
def test_les_dates_affichees_par_successfactors(affichee, attendue):
    from app.connectors.employeurs.successfactors import date_affichee
    assert date_affichee(affichee).timetuple()[:3] == attendue


def test_successfactors_la_liste_s_arrete_a_la_premiere_offre_trop_ancienne(registre):
    site = SiteSuccessFactors([_sf(i, f"Risk Analyst {i}", jours_=i * 10) for i in range(6)])
    c = EmployeursConnector(Sites(banque=site), registre(_employeur_sf("banque")))
    trouvees = c.fetch(_requete(publiee_depuis_jours=15))
    assert sorted(o.titre for o in trouvees) == ["Risk Analyst 0", "Risk Analyst 1"]
    # Deux par page : la seconde montre la première trop ancienne, la troisième
    # n'est jamais demandée.
    assert len([u for _, u, _ in site.appels if "/search/" in u]) == 2


def test_successfactors_sans_date_en_liste_la_veille_lit_une_page(registre):
    site = SiteSuccessFactors([_sf(i, f"Risk Analyst {i}", jours_=i) for i in range(6)], gabarit="tuiles")
    c = EmployeursConnector(Sites(banque=site), registre(_employeur_sf("banque")))
    c.fetch(_requete(publiee_depuis_jours=1))
    assert len([u for _, u, _ in site.appels if "/search/" in u]) == 1


def test_successfactors_une_fiche_complete(registre):
    site = SiteSuccessFactors([_sf(42, "Market Risk Analyst", jours_=3)], gabarit="tuiles")
    c = EmployeursConnector(Sites(banque=site), registre(_employeur_sf("banque")))
    o = c.fetch(_requete())[0]
    assert (o.source_id, o.pays, o.lieu) == ("banque:42", "France", "Paris")
    assert o.description_brute == "Suivi du risque de marché."
    assert o.date_publication.date() == (maintenant() - timedelta(days=3)).date()
    assert not [u for _, u, _ in site.appels if "/services/" in u], "robots.txt l'interdit"


# --- Oracle -----------------------------------------------------------------------------------


class SiteOracle:
    """Oracle Recruiting Cloud : robots.txt en 403 pour tous, liste triée par
    date avec lieux secondaires, fiches par identifiant."""

    def __init__(self, offres):
        self.offres = sorted(offres, key=lambda o: o["jours"])
        self.appels = []

    def get(self, url, **kw):
        self.appels.append(("GET", url, None))
        if url.endswith("/robots.txt"):
            return Reponse(403, None, "W4S-402: Blocked by WAF4SaaS", {})
        if "recruitingCEJobRequisitions?" in url:
            debut = int(url.split("offset=")[1].split(",")[0])
            return Reponse(200, {"items": [{"requisitionList": [{
                "Id": o["id"], "Title": o["titre"], "PrimaryLocation": o["lieu"],
                "PostedDate": (maintenant() - timedelta(days=o["jours"])).date().isoformat(),
                "PrimaryLocationCountry": o["iso"],
                "secondaryLocations": [{"CountryCode": c} for c in o.get("autres", [])],
            } for o in self.offres[debut:debut + 200]]}]}, "", {})
        o = next(o for o in self.offres if f"%22{o['id']}%22" in url)
        return Reponse(200, {"items": [{
            "ExternalDescriptionStr": "<p>Suivi des <b>risques</b>.</p>",
            "ExternalQualificationsStr": "<ul><li>Master</li></ul>",
            "ExternalPostedStartDate": "2026-09-28T09:33:10+00:00",
            "PrimaryLocation": o["lieu"], "PrimaryLocationCountry": o["iso"],
        }]}, "", {})


def _employeur_oracle(hote):
    return {"nom": hote.title(), "logiciel": "oracle",
            "adresse": f"https://{hote}.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001"}


def test_oracle_un_poste_a_new_york_et_a_paris_est_retenu_pour_paris(registre):
    site = SiteOracle([
        {"id": "1", "titre": "Risk Analyst", "jours": 0, "iso": "US", "lieu": "New York", "autres": ["FR"]},
        {"id": "2", "titre": "Risk Analyst", "jours": 0, "iso": "RO", "lieu": "Bucuresti, Romania"},
    ])
    c = EmployeursConnector(Sites(banque=site), registre(_employeur_oracle("banque")))
    trouvees = c.fetch(_requete(pays=("France",)))
    assert [(o.source_id, o.pays) for o in trouvees] == [("banque:1", "France")]


def test_oracle_une_fiche_complete(registre):
    site = SiteOracle([{"id": "7", "titre": "Stage - Risk Analyst", "jours": 0, "iso": "GB", "lieu": "London"}])
    c = EmployeursConnector(Sites(banque=site), registre(_employeur_oracle("banque")))
    o = c.fetch(_requete())[0]
    assert o.description_brute == "Suivi des risques.\n\n- Master"
    assert o.url == "https://banque.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/7"
    assert (o.pays, o.type_contrat) == ("Royaume-Uni", "Stage")


def test_un_pays_hors_du_vocabulaire_est_ecarte_et_non_ignore():
    assert depuis_iso("RO") == "Roumanie"
    assert depuis_nom("Philippines") == "Philippines"
    assert depuis_lieu("Jersey City, NJ, United States") == "États-Unis"


# --- Greenhouse -------------------------------------------------------------------------------


class SiteGreenhouse:
    def __init__(self, offres):
        self.offres, self.appels = offres, []

    def get(self, url, **kw):
        self.appels.append(("GET", url, None))
        if url.endswith("/robots.txt"):
            return Reponse(200, None, "User-agent: *\nDisallow: /embed/\n", {})
        if url.endswith("/jobs"):
            return Reponse(200, {"jobs": [{
                "id": o["id"], "title": o["titre"], "location": {"name": o["lieu"]},
                "absolute_url": f"https://job-boards.greenhouse.io/banque/jobs/{o['id']}",
                "first_published": (maintenant() - timedelta(days=o["jours"])).isoformat() + "-04:00",
            } for o in self.offres]}, "", {})
        return Reponse(200, {"content": "&lt;p&gt;Trade &lt;b&gt;support&lt;/b&gt;.&lt;/p&gt;",
                             "metadata": [{"name": "Time Type", "value": "Internship"}]}, "", {})


def _employeur_gh():
    return {"nom": "Fonds", "logiciel": "greenhouse", "adresse": "https://job-boards.eu.greenhouse.io/fonds"}


class _Api:
    """L'API Greenhouse est sur un hôte commun à tous les tableaux."""

    def __init__(self, site):
        self.site = site

    def get(self, url, **kw):
        assert url.startswith("https://boards-api.greenhouse.io/"), url
        return self.site.get(url, **kw)


def test_greenhouse_un_lieu_a_plusieurs_villes(registre):
    site = SiteGreenhouse([
        {"id": 1, "titre": "Risk Analyst", "lieu": "New York, London, Singapore", "jours": 1},
        {"id": 2, "titre": "Risk Analyst", "lieu": "Amsterdam", "jours": 1},
        {"id": 3, "titre": "Risk Analyst", "lieu": "London", "jours": 60},
    ])
    c = EmployeursConnector(_Api(site), registre(_employeur_gh()))
    trouvees = c.fetch(_requete())
    assert [(o.source_id, o.pays) for o in trouvees] == [("fonds:1", "Royaume-Uni")]


def test_greenhouse_une_fiche_complete(registre):
    site = SiteGreenhouse([{"id": 9, "titre": "Risk Analyst", "lieu": "Paris", "jours": 0}])
    c = EmployeursConnector(_Api(site), registre(_employeur_gh()))
    o = c.fetch(_requete())[0]
    assert (o.description_brute, o.type_contrat, o.pays) == ("Trade support.", "Stage", "France")


# --- Plan du site + JobPosting -------------------------------------------------------------------


class SitePlan:
    """Un site fait maison : robots.txt déclare un index de plans, qui mène au
    plan des offres (en deux langues), chaque fiche balisée en JSON-LD."""

    def __init__(self, offres):
        self.offres, self.appels = offres, []

    def get(self, url, **kw):
        self.appels.append(("GET", url, None))
        if url.endswith("/robots.txt"):
            return Reponse(200, None, "User-agent: *\nDisallow: /search/\nSitemap: https://banque.fr/index.xml\n", {})
        if url.endswith("/index.xml"):
            return Reponse(200, None, "<sitemapindex><sitemap><loc>https://banque.fr/plan-pages.xml</loc></sitemap>"
                                      "<sitemap><loc>https://banque.fr/plan-offres.xml</loc></sitemap></sitemapindex>", {})
        if url.endswith("/plan-offres.xml"):
            urls = "".join(
                f"<url><loc>https://banque.fr/{chemin}/{o['slug']}-{o['id']}-{langue}</loc>"
                f"<lastmod>{(maintenant() - timedelta(days=o['jours'])).isoformat()}+02:00</lastmod></url>"
                for o in self.offres for chemin, langue in (("offres-d-emploi", "fr"), ("job-offers", "en")))
            return Reponse(200, None, f"<urlset>{urls}</urlset>", {})
        if url.endswith("/plan-pages.xml"):
            raise AssertionError("un plan sans offres n'est pas lu")
        o = next(o for o in self.offres if o["id"] in url)
        return Reponse(200, None, '<script type="application/ld+json">' + json.dumps({"@graph": [
            {"@type": "Organization", "name": "Banque"},
            {"@type": "JobPosting", "title": o["titre"], "description": "<p>Risque de <b>crédit</b>.</p>",
             "datePosted": "2026/09/27", "employmentType": "INTERN",
             "jobLocation": {"@type": "Place", "address": {"addressLocality": "Paris", "addressCountry": "FR"}}},
        ]}) + "</script>", {})


def _employeur_plan():
    return {"nom": "Banque", "logiciel": "plan_du_site", "adresse": "https://banque.fr",
            "offres": "/(?:offres-d-emploi|job-offers)/", "identifiant": r"-(\d{6})-(?:fr|en)$", "langue": "fr"}


def test_plan_du_site_une_offre_en_deux_langues_n_est_lue_qu_une_fois(registre):
    site = SitePlan([{"id": "111111", "slug": "analyste-risques-credit", "titre": "Analyste risques crédit &amp; marché", "jours": 0},
                     {"id": "222222", "slug": "analyste-risques-alm", "titre": "Analyste ALM", "jours": 40}])
    c = EmployeursConnector(Sites(banque=site), registre(_employeur_plan()))
    trouvees = c.fetch(_requete())
    assert [(o.source_id, o.titre) for o in trouvees] == [("banque:111111", "Analyste risques crédit & marché")]
    assert trouvees[0].url.endswith("-fr"), "la langue voulue"
    o = trouvees[0]
    assert (o.pays, o.lieu, o.type_contrat, o.description_brute) == ("France", "Paris", "Stage", "Risque de crédit.")
    assert o.date_publication == datetime(2026, 9, 27)


def test_un_index_aux_plans_anonymes_est_suivi_en_entier(registre):
    """Allianz nomme ses plans sitemap1.xml… sitemap4.xml : aucun ne dit
    « job », tous sont lus."""
    class Site(SitePlan):
        def get(self, url, **kw):
            if url.endswith("/index.xml"):
                self.appels.append(("GET", url, None))
                return Reponse(200, None, "<sitemapindex><sitemap><loc>https://banque.fr/plan-offres.xml</loc>"
                                          "</sitemap></sitemapindex>".replace("plan-offres", "sitemap1"), {})
            if url.endswith("/sitemap1.xml"):
                url = url.replace("sitemap1", "plan-offres")
            return super().get(url, **kw)

    site = Site([{"id": "111111", "slug": "analyste-risques", "titre": "Analyste risques", "jours": 0}])
    c = EmployeursConnector(Sites(banque=site), registre(_employeur_plan()))
    assert [o.source_id for o in c.fetch(_requete())] == ["banque:111111"]


def test_le_titre_se_lit_dans_l_adresse():
    from app.connectors.employeurs.plan_du_site import titre_de_l_adresse
    assert titre_de_l_adresse("https://x.fr/offres-d-emploi/analyste-support-trading-2600032A-fr",
                              r"-([0-9A-Z]{8})-(?:fr|en)$") == "analyste support trading"
    # Radancy range l'intitulé avant deux numéros, SuccessFactors avant un.
    assert titre_de_l_adresse("https://careers.x.com/job/new-york/risk-analyst/45831/99354208",
                              r"/(\d+)/?$") == "risk analyst"
    assert titre_de_l_adresse("https://jobs.x.com/job/Warsaw-Securities-Specialist/1439302733/",
                              r"/(\d+)/?$") == "Warsaw Securities Specialist"


def test_le_jobposting_en_guillemets_simples_ou_en_microdonnees():
    from app.connectors.employeurs.plan_du_site import jobposting, microdonnees
    assert jobposting("<script type='application/ld+json'>{\"@type\": \"JobPosting\", \"title\": \"A\"}</script>")["title"] == "A"
    page = ('<div itemscope itemtype="http://schema.org/JobPosting"><h1><span itemprop="title">Risk Analyst</span></h1>'
            '<meta itemprop="addressCountry" content="CH"><meta itemprop="datePosted" content="Sat Sep 26 02:00:00 UTC 2026">'
            '<span itemprop="description"><p>Bâle III.</p></span><div class="applylink">Postuler</div></div>')
    e = microdonnees(page)
    assert (e["title"], e["jobLocation"]["address"]["addressCountry"]) == ("Risk Analyst", "CH")
    assert "Bâle III." in e["description"] and "applylink" not in e["description"]
    assert microdonnees("<p>rien</p>") is None


# --- Groupe BPCE ------------------------------------------------------------------------------


class SiteBpce:
    """recrutement.bpce.fr : un plan des offres publié, une table des routes,
    un contenu par offre. La recherche, interdite par robots.txt, n'existe pas
    ici : un appel à elle ferait échouer le test."""

    ROBOTS = "User-agent: *\nDisallow: /emploi/\nDisallow: /recherche-d'offres\n"

    def __init__(self):
        self.appels = []

    def get(self, url, **kw):
        self.appels.append(("GET", url, None))
        assert "search" not in url, "la recherche n'est jamais utilisée"
        if url.endswith("/robots.txt"):
            return Reponse(200, None, self.ROBOTS, {})
        if "job-sitemap1" in url:
            return Reponse(200, None, "<urlset>" + "".join(
                f"<url><loc>https://recrutement.bpce.fr/job/{slug}/</loc><lastmod>{maintenant().isoformat()}</lastmod></url>"
                for slug in ("stage-analyste-risques-f-h", "conseiller-clientele-f-h")) + "</urlset>", {})
        if "job-sitemap" in url:
            return Reponse(404, None, "", {})
        if "/routes/" in url:
            return Reponse(200, [{"path": "/job/stage-analyste-risques-f-h", "_uid": "job-101-abc"},
                                 {"path": "/job/conseiller-clientele-f-h", "_uid": "job-102-def"},
                                 {"path": "/", "_uid": "page-1-x"}], "", {})
        assert "_uid=job-101-abc" in url, url
        return Reponse(200, {"content": {
            "microdatas": {"@type": "JobPosting", "title": "Stage - Analyste risques (F/H)", "datePosted": "2026-09-27",
                           "hiringOrganization": {"name": "Natixis CIB France"}},
            "top": {"localisations": [{"city": "Paris", "country": "France"}]},
            "main": {"text": "<p>Suivi des <b>risques</b>.</p>"}}}, "", {})


def test_bpce_le_plan_publie_et_la_page_de_l_offre_jamais_la_recherche(registre):
    site = SiteBpce()
    c = EmployeursConnector(Sites(recrutement=site), registre(
        {"nom": "Groupe BPCE", "logiciel": "bpce", "adresse": "https://recrutement.bpce.fr"}))
    [o] = c.fetch(_requete())
    assert (o.titre, o.entreprise, o.pays, o.lieu, o.type_contrat) == (
        "Stage - Analyste risques (F/H)", "Natixis CIB France", "France", "Paris", "Stage")
    assert o.source_id == "groupe-bpce:101"
    assert o.description_brute == "Suivi des risques."


# --- Eightfold ----------------------------------------------------------------------------------


class SiteEightfold:
    ROBOTS = "User-agent: *\nDisallow: /\nAllow: /careers\nAllow: /api/apply\nAllow: /api/pcsx\n"

    def __init__(self, offres):
        self.offres, self.appels = sorted(offres, key=lambda o: o["jours"]), []

    def get(self, url, **kw):
        self.appels.append(("GET", url, None))
        if url.endswith("/robots.txt"):
            return Reponse(200, None, self.ROBOTS, {})
        epoch = lambda o: int((maintenant() - timedelta(days=o["jours"])).timestamp())  # noqa: E731
        if "/api/pcsx/search" in url or "/api/apply/v2/jobs?" in url:
            debut = int(url.split("start=")[1].split("&")[0])
            lieu = url.split("location=")[1].split("&")[0] if "location=" in url else ""
            retenues = [o for o in self.offres if not lieu or lieu.replace("%20", " ") in o["lieu"]]
            cle = "postedTs" if "pcsx" in url else "t_create"
            positions = [{"id": o["id"], "name": o["titre"], "locations": [o["lieu"]], cle: epoch(o)}
                         for o in retenues[debut:debut + 10]]
            return Reponse(200, {"data": {"positions": positions}} if "pcsx" in url else {"positions": positions}, "", {})
        return Reponse(200, {"data": {"jobDescription": "<p>Risques.</p>"}} if "pcsx" in url
                       else {"job_description": "<p>Risques.</p>", "type": "Internship"}, "", {})


def test_eightfold_pcsx_et_v2_pays_par_pays(registre):
    offres = [{"id": 1, "titre": "Risk Analyst", "lieu": "Paris, France", "jours": 0},
              {"id": 2, "titre": "Risk Analyst", "lieu": "Mumbai, India", "jours": 0}]
    site = SiteEightfold(offres)
    c = EmployeursConnector(Sites(ms=site), registre(
        {"nom": "MS", "logiciel": "eightfold", "adresse": "https://ms.eightfold.ai/careers", "domaine": "ms.com"}))
    assert [(o.source_id, o.pays) for o in c.fetch(_requete())] == [("ms:1", "France")]

    site = SiteEightfold(offres)
    c = EmployeursConnector(Sites(hsbc=site), registre(
        {"nom": "HSBC", "logiciel": "eightfold", "adresse": "https://hsbc.eightfold.ai/careers",
         "domaine": "hsbc.com", "par_pays": True}))
    [o] = c.fetch(_requete(pays=("France", "Royaume-Uni")))
    assert (o.pays, o.type_contrat, o.description_brute) == ("France", "Stage", "Risques.")
    # Un pays à la fois, nommé en anglais : sans lieu, l'API choisirait celui de l'appelant.
    lieux = [u.split("location=")[1].split("&")[0] for _, u, _ in site.appels if "v2/jobs?" in u]
    assert lieux == ["France", "United%20Kingdom"]


# --- Jibe (AXA) ---------------------------------------------------------------------------------


class SiteJibe:
    def __init__(self, offres):
        self.offres, self.appels, self.ralentis = sorted(offres, key=lambda o: o["jours"]), [], {}

    def ralentir(self, hote, secondes):
        self.ralentis[hote] = secondes

    def get(self, url, **kw):
        self.appels.append(("GET", url, None))
        if url.endswith("/robots.txt"):
            return Reponse(200, None, "User-agent: *\nAllow: /\ncrawl-delay: 5\n", {})
        page = int(url.split("page=")[1].split("&")[0])
        tranche = self.offres[(page - 1) * 100: page * 100]
        return Reponse(200, {"jobs": [{"data": {
            "req_id": o["id"], "slug": o["id"], "title": o["titre"], "country_code": o["iso"],
            "full_location": "PARIS, France", "employment_type": o.get("type", "FULL_TIME"), "language": "en-us",
            "posted_date": (maintenant() - timedelta(days=o["jours"])).strftime("%Y-%m-%dT%H:%M:%S+0000"),
            "description": "<p>Gestion des risques.</p>"}} for o in tranche]}, "", {})


def test_jibe_tout_vient_de_la_liste_et_le_delai_est_respecte(registre):
    site = SiteJibe([{"id": "1", "titre": "Risk Analyst", "iso": "FR", "jours": 0, "type": "INTERN"},
                     {"id": "2", "titre": "Risk Analyst", "iso": "US", "jours": 0},
                     {"id": "3", "titre": "Risk Analyst", "iso": "FR", "jours": 60}])
    c = EmployeursConnector(Sites(careers=site), registre(
        {"nom": "AXA", "logiciel": "jibe", "adresse": "https://careers.axa.com/careers-home"}))
    [o] = c.fetch(_requete(pays=("France",)))
    assert (o.source_id, o.pays, o.type_contrat, o.description_brute) == ("axa:1", "France", "Stage", "Gestion des risques.")
    assert o.url == "https://careers.axa.com/careers-home/jobs/1?lang=en-us"
    assert site.ralentis == {"careers.axa.com": 5.0}, "crawl-delay de robots.txt transmis au client"
    assert [u for _, u, _ in site.appels if "/api/jobs" in u and "page=2" in u] == []


def test_le_client_respecte_le_delai_demande(monkeypatch):
    from app.connectors import http as module_http
    from app.connectors.http import ClientHttp
    attentes = []
    monkeypatch.setattr(module_http.time, "sleep", lambda s: attentes.append(round(s)))
    c = ClientHttp(user_agent="t", requetes_par_seconde=1.0)
    c.ralentir("Lent.example", 5)
    for _ in range(2):
        c._attendre_son_tour("https://lent.example/x")
        c._attendre_son_tour("https://rapide.example/x")
    assert attentes == [5, 1], "5 s pour le site qui l'a demandé, 1 s pour les autres"


# --- Beesite (Deutsche Bank) ------------------------------------------------------------------


class SiteBeesite:
    def __init__(self, offres):
        self.offres, self.appels = sorted(offres, key=lambda o: o["jours"]), []

    def get(self, url, **kw):
        from urllib.parse import unquote
        self.appels.append(("GET", url, None))
        if url.endswith("/robots.txt"):
            return Reponse(404, None, "", {})
        if "/jobhtml/" in url:
            return Reponse(200, {"html": "<div><h1>Poste</h1><p>Risque de crédit.</p></div>"}, "", {})
        donnees = json.loads(unquote(url.split("data=")[1]))
        debut = donnees["SearchParameters"]["FirstItem"] - 1
        return Reponse(200, {"SearchResult": {"SearchResultItems": [{"MatchedObjectDescriptor": {
            "PositionID": o["id"], "PositionTitle": o["titre"], "PositionURI": f"/index.php?id={o['id']}",
            "PositionLocation": [{"CityName": "Paris", "CountryName": o["pays"]}],
            "PositionOfferingType": [{"Name": "Unbefristet"}],
            "PublicationStartDate": (maintenant() - timedelta(days=o["jours"])).date().isoformat(),
        }} for o in self.offres[debut:debut + 100]]}}, "", {})


def test_beesite_pays_et_contrat_en_allemand(registre):
    site = SiteBeesite([{"id": "1", "titre": "Credit Risk Analyst", "pays": "Frankreich", "jours": 0},
                        {"id": "2", "titre": "Credit Risk Analyst", "pays": "Rumänien", "jours": 0}])
    c = EmployeursConnector(Sites(apidb=site), registre(
        {"nom": "DB", "logiciel": "beesite", "adresse": "https://apidb.beesite.de",
         "fiche": "https://careers.db.com/job/{id}"}))
    [o] = c.fetch(_requete(pays=("France",)))
    # « Unbefristet » est un CDI : le motif « befristet » le lisait CDD.
    assert (o.pays, o.type_contrat, o.url, o.description_brute) == (
        "France", "CDI", "https://careers.db.com/job/1", "Poste\nRisque de crédit.")


# --- Recruitee, Pinpoint ------------------------------------------------------------------------


class SiteApi:
    """Une API publique qui donne tout d'un coup."""

    def __init__(self, reponse):
        self.reponse, self.appels = reponse, []

    def get(self, url, **kw):
        self.appels.append(("GET", url, None))
        if url.endswith("/robots.txt"):
            return Reponse(200, None, "User-agent: *\nDisallow: /admin\n", {})
        return Reponse(200, self.reponse, "", {})


def test_recruitee_et_les_offres_qui_n_en_sont_pas(registre):
    publiee = maintenant().strftime("%Y-%m-%d %H:%M:%S UTC")
    offre = lambda i, titre: {"id": i, "title": titre, "careers_url": f"https://c.fr/o/{i}", "country_code": "FR",  # noqa: E731
                              "published_at": publiee, "employment_type_code": "internship",
                              "description": "<p>Fonds.</p>", "requirements": "<p>Risques.</p>"}
    site = SiteApi({"offers": [offre(1, "Risk Analyst Intern"), offre(2, "CLOSED: Risk Analyst"),
                               offre(3, "Open application - Risk")]})
    c = EmployeursConnector(Sites(fonds=site), registre(
        {"nom": "Fonds", "logiciel": "recruitee", "adresse": "https://fonds.recruitee.com"}))
    [o] = c.fetch(_requete())
    assert (o.source_id, o.pays, o.type_contrat, o.description_brute) == ("fonds:1", "France", "Stage", "Fonds.\n\nRisques.")


def test_pinpoint_sans_date(registre):
    site = SiteApi({"data": [{"id": 5, "title": "Risk Analyst", "location": {"city": "Frankfurt"},
                              "url": "https://p.fr/postings/5", "employment_type": "internship",
                              "description": "<p>PE.</p>"}]})
    c = EmployeursConnector(Sites(fonds=site), registre(
        {"nom": "Fonds", "logiciel": "pinpoint", "adresse": "https://fonds.pinpointhq.com"}))
    [o] = c.fetch(_requete(pays=("Allemagne",)))
    assert (o.pays, o.type_contrat, o.date_publication) == ("Allemagne", "Stage", None)


# --- BrassRing (UBS) --------------------------------------------------------------------------


class SiteBrassRing:
    """Les offres embarquées dans un champ caché, en JSON échappé en HTML."""

    def __init__(self, offres):
        self.offres, self.appels = offres, []

    @staticmethod
    def _page(donnees):
        from html import escape
        return Reponse(200, None, f'<input id="preLoadJSON" type="hidden" value="{escape(json.dumps(donnees))}" />', {})

    def get(self, url, **kw):
        self.appels.append(("GET", url, None))
        if url.endswith("/robots.txt"):
            return Reponse(404, None, "", {})
        q = lambda **kv: [{"QuestionName": k, "Value": v} for k, v in kv.items()]  # noqa: E731
        if "PageType=searchResults" in url:
            return self._page({"searchResultsResponse": {"Jobs": {"Job": [
                {"Questions": q(reqid=o["id"], jobtitle=o["titre"], formtext23="",
                                lastupdated=(maintenant() - timedelta(days=o["jours"])).strftime("%d-%b-%Y"))}
                for o in self.offres]}}})
        return self._page({"Jobdetails": {"JobDetailQuestions": q(
            formtext23="France", City="Paris", **{"Job Type": "Internship",
                                                  "Key responsibilities": "Suivre le risque de marché au quotidien, " * 3})}})


def test_brassring_le_pays_vient_de_la_fiche(registre):
    site = SiteBrassRing([{"id": "7", "titre": "Market Risk Analyst", "jours": 0}])
    c = EmployeursConnector(Sites(jobs=site), registre(
        {"nom": "UBS", "logiciel": "brassring",
         "adresse": "https://jobs.ubs.com/TGnewUI/Search/Home/HomeWithPreLoad?partnerid=1&siteid=2"}))
    [o] = c.fetch(_requete(pays=("France",)))
    assert (o.pays, o.lieu, o.type_contrat) == ("France", "Paris", "Stage")
    assert o.description_brute.startswith("Key responsibilities\n")


# --- La politesse, les pannes ---------------------------------------------------------------


def test_robots_txt_qui_interdit_n_est_pas_franchi(registre):
    site = SiteWorkday([_offre("Risk Analyst")], robots="User-agent: *\nDisallow: /\n")
    c = EmployeursConnector(Sites(banque=site), registre(_employeur("banque")))
    with pytest.raises(ErreurConnecteur):
        c.fetch(_requete())
    assert [m for m, *_ in site.appels] == ["GET"], "seul robots.txt a été lu"
    assert "robots.txt" in c.pannes["Banque"]


@pytest.mark.parametrize("url, attendu", [
    # Eightfold : tout est interdit sauf ce qui est nommé. `urllib.robotparser`
    # appliquait la première règle et interdisait ce que le site autorise.
    ("https://ms.eightfold.ai/api/pcsx/search?domain=x", True),
    ("https://ms.eightfold.ai/careers", True),
    ("https://ms.eightfold.ai/admin", False),
    ("https://ms.eightfold.ai/", True),                 # Allow: /$
    ("https://ms.eightfold.ai/x/", False),
    # La règle la plus précise l'emporte, même interdite après une autorisation.
    ("https://ms.eightfold.ai/careers/secret/1", False),
    # Joker et ancre de fin.
    ("https://ms.eightfold.ai/careers?page=1", False),
    ("https://ms.eightfold.ai/careers?page=12", True),
    # À précision égale, l'autorisation l'emporte.
    ("https://ms.eightfold.ai/egal", True),
])
def test_robots_txt_selon_la_rfc_9309(url, attendu):
    from app.connectors.employeurs.robots import Regles
    texte = ("User-agent: Googlebot\nDisallow: /careers\n\n"
             "User-agent: *\nDisallow: /\nAllow: /$\nAllow: /careers\nAllow: /api/pcsx\n"
             "Disallow: /careers/secret\nDisallow: /*?page=1$\nDisallow: /egal\nAllow: /egal\n"
             "Sitemap: https://ms.eightfold.ai/plan.xml\n")
    regles = Regles(texte, "DreamJob")
    assert regles.autorise(url) is attendu
    assert regles.site_maps() == ["https://ms.eightfold.ai/plan.xml"]


@pytest.mark.parametrize("signal, permis", [
    ("search=no, ai-train=no, ai-input=no", False),       # Antin Infrastructure Partners
    ("search=yes, ai-train=no, ai-input=yes", True),      # Kepler Cheuvreux : on n'entraîne rien
    ("search=yes, ai-input=no", False),                   # la lettre donne l'annonce à un modèle
    ("ai-train=no", True),
])
def test_content_signal(signal, permis):
    """Ce que le site permet de faire de son contenu : DreamJob le range pour
    le chercher et le donne à un modèle pour écrire la lettre."""
    from app.connectors.employeurs.robots import Regles
    regles = Regles(f"User-Agent: aihitdata\nDisallow: /\n\nUser-Agent: *\nDisallow: /app/\n"
                    f"Content-Signal: {signal}\n", "DreamJob")
    assert regles.usages_permis() is permis
    assert regles.autorise("https://x.teamtailor.com/jobs/1-analyste")


def test_un_site_qui_refuse_la_recherche_n_est_pas_collecte(registre):
    site = SiteWorkday([_offre("Risk Analyst")],
                       robots="User-agent: *\nAllow: /\nContent-Signal: search=no, ai-input=no\n")
    c = EmployeursConnector(Sites(banque=site), registre(_employeur("banque")))
    with pytest.raises(ErreurConnecteur):
        c.fetch(_requete())
    assert [m for m, *_ in site.appels] == ["GET"], "seul robots.txt a été lu"


def test_le_groupe_qui_nomme_notre_robot_passe_avant_l_etoile():
    from app.connectors.employeurs.robots import Regles
    texte = "User-agent: *\nDisallow: /\n\nUser-agent: DreamJob\nUser-agent: autre\nDisallow: /prive\n"
    assert Regles(texte, "DreamJob").autorise("https://x.fr/offres")
    assert not Regles(texte, "DreamJob").autorise("https://x.fr/prive/1")
    assert not Regles(texte, "AutreRobot").autorise("https://x.fr/offres")
    assert Regles("User-agent: *\nDisallow:\n", "DreamJob").autorise("https://x.fr/tout")


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
