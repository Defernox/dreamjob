"""Le plan du site et le balisage JobPosting : le format que Google exige.

Pour paraître dans Google for Jobs, un site carrières publie ses offres dans son
plan du site (`sitemap.xml`) et balise chaque fiche en JSON-LD `JobPosting`
(schema.org). C'est un format standard, pensé pour être lu par des programmes :
il marche quel que soit le logiciel, y compris sur les sites faits maison.

Société Générale, vérifié le 2026-09-28 : `robots.txt` interdit `/search/` —
la recherche du site n'est donc pas utilisée — et publie `sitemap.xml`, qui
liste 1 046 offres avec leur date de modification (vingt à cinquante nouvelles
par jour) ; chaque fiche porte son JobPosting.

Ce que la liste ne donne pas, l'adresse le donne : on y lit l'intitulé
(« …/offres-d-emploi/analyste-support-aux-operations-de-trading-2600032A-fr »),
assez pour la comparaison avec les recherches. La fiche n'est ouverte que pour
une offre nouvelle qui répond.

Options dans `employeurs.yaml` :
- `plan` : l'adresse du plan du site (sinon, celui que déclare robots.txt) ;
- `offres` : motif que suit l'adresse d'une offre ;
- `identifiant` : motif dont le premier groupe identifie l'offre — une même
  offre publiée en deux langues n'est alors lue qu'une fois ;
- `langue` : la version gardée quand il y en a deux.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import unescape
from urllib.parse import unquote, urljoin, urlparse

from .commun import Annonce, contrat, texte
from .logiciel import Logiciel
from .pays import depuis_iso, depuis_lieu, depuis_nom
from .registre import Employeur

# Hays enrobe adresses et dates de CDATA, noyées d'espaces.
_CDATA = r"\s*(?:<!\[CDATA\[\s*)?([^<\s\]]+)\s*(?:\]\]>)?\s*"
_LOC = re.compile(rf"<(sitemap|url)>\s*<loc>{_CDATA}</loc>(?:\s*<lastmod>{_CDATA}</lastmod>)?", re.S)
# Guillemets simples, doubles ou absents : chaque site écrit la balise à sa façon.
_JSONLD = re.compile(r"""<script[^>]*type=["']?application/ld\+json["']?[^>]*>(.*?)</script>""", re.S | re.I)
_CONTRATS = {"INTERN": "Stage", "INTERNSHIP": "Stage", "TEMPORARY": "CDD", "CONTRACTOR": "Freelance",
             "APPRENTICESHIP": "Alternance"}
PLANS_MAX = 20


def _date(valeur: str | None) -> datetime | None:
    if not valeur:
        return None
    valeur = valeur.strip().replace("/", "-")
    try:
        instant = datetime.fromisoformat(valeur)
    except ValueError:
        # Microdonnées SuccessFactors : « Sat Sep 26 02:00:00 UTC 2026 ».
        for format_ in ("%Y-%m-%d", "%a %b %d %H:%M:%S %Z %Y"):
            try:
                instant = datetime.strptime(valeur if "%Z" in format_ else valeur[:10], format_)
                break
            except ValueError:
                continue
        else:
            return None
    if instant.tzinfo is not None:
        instant = instant.astimezone(timezone.utc).replace(tzinfo=None)
    return instant


def jobposting(html: str) -> dict | None:
    """Le premier JobPosting des blocs JSON-LD d'une page (listes et `@graph`
    compris)."""
    for bloc in _JSONLD.findall(html):
        try:
            # Michael Page laisse des sauts de ligne bruts dans ses chaînes :
            # invalide au sens strict, parfaitement lisible.
            donnees = json.loads(bloc.strip(), strict=False)
        except json.JSONDecodeError:
            continue
        pile = donnees if isinstance(donnees, list) else [donnees]
        while pile:
            e = pile.pop(0)
            if not isinstance(e, dict):
                continue
            types = e.get("@type")
            if types == "JobPosting" or (isinstance(types, list) and "JobPosting" in types):
                return e
            pile.extend(e.get("@graph") or [])
    return None


_FINS_DESCRIPTION = ("applylink", 'class="jobFooter', 'id="similar-jobs', "<footer", 'class="social')


def _itemprop(html: str, nom: str) -> str:
    """La valeur d'une propriété : attribut `content`, sinon texte de l'élément."""
    for motif in (rf'itemprop="{nom}"[^>]*content="([^"]*)"', rf'content="([^"]*)"[^>]*itemprop="{nom}"',
                  rf'itemprop="{nom}"[^>]*>(.*?)</'):
        if m := re.search(motif, html, re.S):
            return " ".join(unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split())
    return ""


def microdonnees(html: str) -> dict | None:
    """Le JobPosting d'une page balisée en microdonnées plutôt qu'en JSON-LD —
    la même norme schema.org, sous une autre forme (SuccessFactors, notamment)."""
    if not re.search(r"schema\.org/JobPosting", html):
        return None
    debut = html.find('itemprop="description"')
    description = ""
    if debut >= 0:
        # La marque de fin est dans une balise : on coupe au début de celle-ci.
        fins = [html.rfind("<", debut, i) for i in (html.find(f, debut) for f in _FINS_DESCRIPTION) if i > 0]
        fins = [i for i in fins if i > debut]
        bloc = html[debut:min(fins) if fins else debut + 30000]
        description = bloc[bloc.find(">") + 1:]
    return {
        "title": _itemprop(html, "title"),
        "description": description,
        "datePosted": _itemprop(html, "datePosted"),
        "jobLocation": {"address": {"addressLocality": _itemprop(html, "addressLocality"),
                                    "addressCountry": _itemprop(html, "addressCountry")}},
        "employmentType": _itemprop(html, "employmentType"),
    }


_OG_TITRE = re.compile(r'<meta[^>]*property="og:title"[^>]*content="([^"]*)"', re.I)
# La valeur est souvent noyée d'espaces et de sauts de ligne : on les laisse
# hors de la capture, sans quoi elle dépassait la longueur permise.
_ETIQUETTE = r">\s*(?:{})\s*:?\s*</[^>]+>(?:\s*<[^>]+>)*\s*([^<]{{2,80}}?)\s*<"
_LIEU_ETIQUETTE = re.compile(_ETIQUETTE.format(
    "Location|Locations|Lieu du poste|Localisation du poste|Lieu|City|Office|Standort|Arbeitsort|Ort|Sede"
    "|Città"), re.I)
_PAYS_ETIQUETTE = re.compile(_ETIQUETTE.format("Country|Land|Pays|Paese"), re.I)
_CONTRAT_ETIQUETTE = re.compile(_ETIQUETTE.format(
    "Type de contrat|Contrat|Contract type|Contract|Employment type|Vertragsart|Tipo di contratto"), re.I)


def bloc(html: str, options: dict) -> dict | None:
    """Dernier recours, pour un site sans aucun balisage (Avature : BCE,
    Bloomberg) : le texte entre deux repères que l'employeur déclare dans
    employeurs.yaml (`bloc`, `fin_bloc`), l'intitulé dans `og:title`."""
    debut_marque = options.get("bloc")
    if not debut_marque or (debut := html.find(debut_marque)) < 0:
        return None
    # Plusieurs repères de fin possibles (« tpt_socialShare|<footer ») : le
    # premier rencontré ferme l'annonce.
    fins = [i for i in (html.find(m, debut) for m in str(options.get("fin_bloc") or "").split("|") if m) if i > 0]
    corps = html[debut:min(fins) if fins else debut + 30000]
    corps = corps[corps.find(">") + 1:]
    fin_balise = corps.rfind("<")
    og = _OG_TITRE.search(html)
    titre = og.group(1) if og else ""
    lieu = _LIEU_ETIQUETTE.search(corps)
    pays = _PAYS_ETIQUETTE.search(corps)
    # La Banque Postale met dans og:title le titre de la liste : l'intitulé
    # est alors celui du <h1> (`titre_h1`).
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    if options.get("titre_h1") and h1:
        titre = " ".join(re.sub(r"<[^>]+>", " ", h1.group(1)).split())
    # Marex : deux <h1>, le premier est le titre de la rubrique. Le motif
    # (`titre_motif`, un groupe) désigne le bon.
    if (motif := options.get("titre_motif")) and (m := re.search(motif, html, re.S)):
        titre = " ".join(re.sub(r"<[^>]+>", " ", m.group(1)).split())
    type_ = _CONTRAT_ETIQUETTE.search(corps)
    # Linedata range la ville dans un bloc sans étiquette : `lieu_motif` (un
    # groupe) la désigne.
    if motif_lieu := options.get("lieu_motif"):
        lieu = re.search(motif_lieu, html, re.S)
    ville = " ".join(re.sub(r"<[^>]+>", " ", unescape(lieu.group(1))).split()) if lieu else ""
    return {"title": unescape(titre),
            "employmentType": unescape(type_.group(1)).strip() if type_ else "",
            "description": corps[:fin_balise] if fin_balise > 0 else corps,
            "jobLocation": {"address": {"addressLocality": ville,
                                        "addressCountry": unescape(pays.group(1)).strip() if pays else ""}}}


def titre_de_l_adresse(url: str, identifiant: str | None) -> str:
    """« …/analyste-support-trading-2600032A-fr » → « analyste support trading ».

    Le dernier segment qui porte des lettres : Radancy range l'intitulé avant
    deux numéros (`/job/new-york/risk-analyst/45831/99354208`), SuccessFactors
    avant un (`/job/Zurich-Payment-Specialist/1422930133/`).
    """
    chemin = unquote(urlparse(url).path)
    if identifiant and (m := re.search(identifiant, chemin)):
        chemin = chemin[:m.start()] + chemin[m.end():]
    segments = [s for s in chemin.split("/") if re.search(r"[^\W\d_]{2}", s)]
    dernier = segments[-1] if segments else ""
    dernier = re.sub(r"\.(?:html?|aspx?|php)$", "", dernier)
    return " ".join(re.sub(r"[-_+]+", " ", dernier).split())


def _lieu(e: dict) -> tuple[str, str]:
    """(ville, pays) d'un JobPosting, dont `jobLocation` peut être une liste."""
    lieux = e.get("jobLocation") or []
    lieux = lieux if isinstance(lieux, list) else [lieux]
    for lieu in lieux:
        adresse = (lieu or {}).get("address") or {} if isinstance(lieu, dict) else {}
        if isinstance(adresse, str):
            return adresse, depuis_lieu(adresse)
        ville = adresse.get("addressLocality") or ""
        pays = adresse.get("addressCountry") or ""
        if isinstance(pays, dict):
            pays = pays.get("name") or ""
        pays = depuis_iso(pays) if len(pays) == 2 else depuis_nom(pays)
        if ville or pays:
            return ville, pays or depuis_lieu(ville)
    return "", ""


class PlanDuSite(Logiciel):
    cle = "plan_du_site"

    def _plans(self, employeur: Employeur) -> list[str]:
        if plan := employeur.options.get("plan"):
            # MSCI publie un plan par portail régional : une liste est acceptée.
            return list(plan) if isinstance(plan, list) else [plan]
        racine = re.match(r"https?://[^/]+", employeur.adresse).group(0)
        regles = self.robots._pour(racine)
        declares = list(regles.site_maps() or []) if regles is not None else []
        return declares or [f"{racine}/sitemap.xml"]

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        motif = re.compile(employeur.options.get("offres", r"/(?:job|jobs|offre|offres|emploi|career|vacanc)"),
                           re.I)
        identifiant = employeur.options.get("identifiant")
        langue = employeur.options.get("langue")
        a_lire, lus = self._plans(employeur), 0
        vues: dict[str, Annonce] = {}
        while a_lire and lus < PLANS_MAX:
            plan = a_lire.pop(0)
            lus += 1
            self.verifier(plan)
            # Relu à chaque passe de veille : redemandé sous condition (304 = inchangé).
            xml = self.http.get(plan, utiliser_cache=False, revalider=True).texte
            sous_plans = []
            for balise, loc, modifie in _LOC.findall(xml):
                # Une adresse de plan est du XML : « &amp; » y vaut « & » (Scope,
                # Commerzbank). Gardée échappée, elle menait à une page d'erreur.
                loc = urljoin(plan, unescape(loc))
                if balise == "sitemap":
                    sous_plans.append(loc)
                    continue
                if not motif.search(loc):
                    continue
                publiee = _date(modifie)
                if publiee is not None and publiee < depuis:
                    continue
                m = re.search(identifiant, loc) if identifiant else None
                ident = m.group(1) if m else urlparse(loc).path.rstrip("/").rsplit("/", 1)[-1]
                deja = vues.get(ident)
                # Une offre en deux langues : on garde la langue voulue.
                if deja and not (langue and loc.rstrip("/").endswith(f"-{langue}")):
                    continue
                # iCIMS finit ses adresses par « /job » : `titre_adresse` (un
                # groupe) dit où est l'intitulé.
                m_titre = re.search(employeur.options["titre_adresse"], loc) \
                    if employeur.options.get("titre_adresse") else None
                titre = (" ".join(re.sub(r"[-_+]+", " ", unquote(m_titre.group(1))).split()) if m_titre
                         else titre_de_l_adresse(loc, identifiant))
                vues[ident] = Annonce(ident=ident, titre=titre, url=loc, publiee_le=publiee)
            # Un index de plans : ceux qui parlent d'offres d'abord ; s'il n'y
            # en a aucun (Allianz : sitemap1.xml… sitemap4.xml), tous.
            parlants = [s for s in sous_plans
                        if motif.search(s) or re.search(r"job|offre|career|vacanc|position", s, re.I)]
            a_lire.extend(parlants or sous_plans)
        annonces = sorted(vues.values(), key=lambda a: a.publiee_le or datetime.min, reverse=True)
        return annonces

    def completer(self, employeur: Employeur, annonce: Annonce) -> Annonce:
        # iCIMS sert l'offre dans un cadre : la page publique reste l'adresse
        # de l'offre, le cadre (`fiche_suffixe`) est ce qu'on lit.
        fiche = annonce.url + str(employeur.options.get("fiche_suffixe") or "")
        self.verifier(fiche)
        html = self.http.get(fiche).texte
        e = jobposting(html) or microdonnees(html)
        secours = bloc(html, employeur.options)
        if e is None:
            e = secours
        elif secours and (employeur.options.get("description_bloc")
                          or len(texte(str(e.get("description") or ""))) < 200):
            # UniCredit balise l'intitulé et la date, pas la description : elle
            # vient alors du bloc déclaré, le reste du balisage est gardé.
            # Oddo BHF n'y met que les missions, sans le profil recherché :
            # `description_bloc` préfère le bloc, qui a tout.
            e = {**e, "description": secours["description"],
                 "title": e.get("title") or secours["title"],
                 "jobLocation": e.get("jobLocation") or secours["jobLocation"],
                 "employmentType": e.get("employmentType") or secours["employmentType"]}
            if employeur.options.get("titre_motif"):
                e["title"] = secours["title"] or e.get("title")
        if e is None:
            return annonce
        # « Retail &amp; Online » : le titre JSON-LD est parfois échappé en HTML.
        annonce.titre = " ".join(unescape(str(e.get("title") or annonce.titre)).split())
        annonce.description = texte(str(e.get("description") or ""))
        # Ce que la liste savait déjà (le lieu d'une interface JSON) n'est pas
        # effacé par une fiche qui ne le dit pas.
        lieu, pays = _lieu(e)
        if not lieu and secours:
            lieu = _lieu(secours)[0]
        annonce.lieu, annonce.pays = lieu or annonce.lieu, pays or annonce.pays
        # « Warsaw Financial Securities Specialist » : sans lieu balisé, la ville
        # de l'intitulé ou de l'adresse dit le pays.
        # Avature chez Macquarie : la première ligne de l'annonce est le lieu
        # (« Sydney ») ; on ne la lit que courte, pour ne pas prendre une phrase.
        # Marex la met en deuxième ligne, sous l'intitulé (« London, GB, »).
        courtes = [ligne for ligne in annonce.description.split("\n")[:4] if 0 < len(ligne) <= 40]
        annonce.pays = (annonce.pays or depuis_lieu(annonce.titre)
                        or depuis_lieu(titre_de_l_adresse(annonce.url, None))
                        or next((p for p in map(depuis_lieu, courtes) if p), ""))
        annonce.publiee_le = _date(e.get("datePosted")) or annonce.publiee_le
        types = e.get("employmentType") or []
        types = [types] if isinstance(types, str) else types
        annonce.contrat = (contrat(annonce.titre, *types)
                           or next((_CONTRATS[t.upper()] for t in types if t.upper() in _CONTRATS), "")
                           or annonce.contrat)
        annonce.brut["date_limite"] = e.get("validThrough")
        annonce.complete = True
        return annonce
