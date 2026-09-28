"""SuccessFactors (SAP) : CFM, Pictet, Partners Group, Nomura, Generali, Fitch,
Swiss Re, SMBC, Belfius…

Les sites « Recruiting Marketing » de SuccessFactors sont des pages serveur.
Vérifié le 2026-09-28 sur jobs.cfm.com, jobs.partnersgroup.com,
careers.nomura.com, careers.swissre.com :

- `robots.txt` interdit `/services/` — donc le flux RSS que ces sites
  proposent — mais pas `/search/` ni `/job/` ;
- la recherche se trie par date (`sortColumn=referencedate`) et se pagine par
  `startrow`, de 20 à 100 offres par page selon le site ;
- deux gabarits : un tableau (`data-row`) ou des tuiles (`job-tile`), et chaque
  site choisit ses colonnes — lieu toujours, date souvent, service parfois. On
  lit chaque offre à ses marques (`jobTitle-link`, `jobLocation`, `jobDate`,
  `-section-…-value`), pas à sa position ;
- la fiche porte des microdonnées schema.org : pays en code ISO, date de
  publication, description.
"""

from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from urllib.parse import urljoin

from ...models.base import maintenant
from .commun import Annonce, contrat, texte
from .logiciel import Logiciel
from .pays import depuis_iso, depuis_lieu
from .registre import Employeur

JOURS_PREMIERE_PAGE = 3
_ANCRE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S)
_LIEN = re.compile(r'href="([^"]*/job/[^"]*?/(\d+)/?)"')
_LIEU = re.compile(r'class="jobLocation[^"]*"[^>]*>(.*?)</span>|-section-location-value"[^>]*>(.*?)</div>', re.S)
_DATE_LISTE = re.compile(r'class="jobDate[^"]*"[^>]*>([^<]+)<|-section-date-value"[^>]*>([^<]+)<', re.S)
_META = r'itemprop="{}"[^>]*content="([^"]*)"'
_MOIS = {
    "jan": 1, "janv": 1, "feb": 2, "fev": 2, "fév": 2, "févr": 2, "mar": 3, "mars": 3, "apr": 4, "avr": 4,
    "may": 5, "mai": 5, "jun": 6, "juin": 6, "jul": 7, "juil": 7, "aug": 8, "aou": 8, "aoû": 8, "août": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12, "déc": 12, "mär": 3, "okt": 10, "dez": 12,
    "mag": 5, "giu": 6, "lug": 7, "ago": 8, "set": 9, "ott": 10, "dic": 12, "gen": 1, "gennaio": 1,
}
_JOURS = re.compile(r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b")
_FINS = ("applylink", 'class="jobFooter', 'id="similar-jobs', "<footer", 'class="social')


def _propre(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment or "")).split())


def date_affichee(texte_: str) -> datetime | None:
    """« 28 Sept 2026 », « Sep 28, 2026 », « 28 sept. 2026 », « 28/09/2026 »,
    « 28.09.2026 ». Illisible : None, et rien n'est jeté sur cette date."""
    t = texte_.strip().lower().replace(".", " ").replace(",", " ")
    # « mardi » commence comme « mars » : les jours de la semaine d'abord.
    t = _JOURS.sub(" ", t)
    if m := re.search(r"\b(\d{1,2})[/ ](\d{1,2})[/ ](\d{4})\b", t):
        jour, mois, annee = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        jour_ = re.search(r"\b(\d{1,2})\b", t)
        annee_ = re.search(r"\b(\d{4})\b", t)
        mois_ = next((n for mot in re.findall(r"[a-zéûä]+", t) for cle, n in _MOIS.items()
                      if mot.startswith(cle) and len(mot) <= len(cle) + 5), None)
        if not (jour_ and annee_ and mois_):
            return None
        jour, mois, annee = int(jour_.group(1)), mois_, int(annee_.group(1))
    try:
        return datetime(annee, mois, jour)
    except ValueError:
        return None


class SuccessFactors(Logiciel):
    cle = "successfactors"

    @staticmethod
    def _base(employeur: Employeur) -> str:
        return re.match(r"https?://[^/]+", employeur.adresse).group(0)

    def _page(self, employeur: Employeur, debut: int) -> str:
        base = self._base(employeur)
        chemin = employeur.options.get("recherche", "/search/")
        url = f"{base}{chemin}?q=&sortColumn=referencedate&sortDirection=desc&startrow={debut}"
        self.verifier(url)
        return self.http.get(url, utiliser_cache=False).texte

    def _lire(self, html: str, base: str) -> list[Annonce]:
        positions: dict[str, tuple[int, str, str]] = {}
        for attributs, contenu in ((m.group(1), m) for m in _ANCRE.finditer(html)):
            if "jobTitle-link" not in attributs:
                continue
            lien = _LIEN.search(attributs)
            if lien and lien.group(2) not in positions:
                positions[lien.group(2)] = (contenu.start(), unescape(lien.group(1)), _propre(contenu.group(2)))
        ordre = sorted(positions.items(), key=lambda x: x[1][0])
        annonces = []
        for i, (ident, (debut, chemin, titre)) in enumerate(ordre):
            fin = ordre[i + 1][1][0] if i + 1 < len(ordre) else debut + 6000
            bloc = html[debut:fin]
            lieu_m = _LIEU.search(bloc)
            lieu = re.sub(r"\+\s*\d+\s*(?:more|autres?|weitere)\W*$", "", _propre(
                (lieu_m.group(1) or lieu_m.group(2)) if lieu_m else "")).strip(" ,")
            date_m = _DATE_LISTE.search(bloc)
            annonces.append(Annonce(
                ident=ident, titre=titre, url=urljoin(base, chemin), lieu=lieu, pays=depuis_lieu(lieu),
                publiee_le=date_affichee(date_m.group(1) or date_m.group(2)) if date_m else None,
                contrat=contrat(titre),
            ))
        return annonces

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        base = self._base(employeur)
        # Sans date en liste, la veille ne peut s'arrêter à la première offre
        # trop ancienne : la première page (les plus récentes) lui suffit.
        if (maintenant() - depuis).days <= JOURS_PREMIERE_PAGE:
            pages_max = 1
        vues: dict[str, Annonce] = {}
        debut = 0
        for _ in range(pages_max):
            lues = self._lire(self._page(employeur, debut), base)
            nouvelles = [a for a in lues if a.ident not in vues]
            if not nouvelles:
                break
            trop_vieille = False
            for a in nouvelles:
                if a.publiee_le is not None and a.publiee_le < depuis.replace(hour=0, minute=0):
                    trop_vieille = True
                    break
                vues[a.ident] = a
            if trop_vieille:
                break
            debut += len(lues)
        return [a for a in vues.values() if not (pays and a.pays and a.pays not in pays)]

    def completer(self, employeur: Employeur, annonce: Annonce) -> Annonce:
        self.verifier(annonce.url)
        html = self.http.get(annonce.url).texte

        def meta(nom: str) -> str:
            m = re.search(_META.format(nom), html)
            return unescape(m.group(1)).strip() if m else ""

        debut = html.find('class="jobdescription"')
        if debut < 0:
            debut = html.find('itemprop="description"')
        if debut >= 0:
            # La marque de fin est dans une balise (`<div class="applylink">`) :
            # on coupe au début de celle-ci, sans quoi « <div class=" » resterait.
            fins = [html.rfind("<", debut, i) for i in (html.find(f, debut) for f in _FINS) if i > 0]
            fins = [i for i in fins if i > debut]
            corps = html[debut:min(fins) if fins else debut + 30000]
            annonce.description = texte(corps[corps.find(">") + 1:])
        annonce.pays = depuis_iso(meta("addressCountry")) or annonce.pays
        annonce.lieu = meta("addressLocality") or annonce.lieu
        if publiee := meta("datePosted"):
            try:
                annonce.publiee_le = datetime.strptime(publiee, "%a %b %d %H:%M:%S %Z %Y")
            except ValueError:
                annonce.publiee_le = date_affichee(publiee) or annonce.publiee_le
        annonce.complete = True
        return annonce
