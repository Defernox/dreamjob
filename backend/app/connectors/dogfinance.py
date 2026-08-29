"""Connecteur DogFinance — offres spécialisées finance.

**Ce qui a été vérifié avant d'écrire ce connecteur** (2026-08-30) :

- `robots.txt` autorise `/`, publie trois sitemaps d'offres et n'interdit, de ce
  qui nous concerne, que `/offres?*` — la **recherche filtrée**, que ce
  connecteur n'utilise jamais ;
- les CGU ne comportent aucune clause sur l'extraction automatisée, les robots
  ou le moissonnage (cherché : extraction, aspiration, robot, moissonnage,
  crawl, scraping, automatisé — zéro occurrence) ;
- elles réservent en revanche l'usage des textes « sans le consentement écrit
  de l'Editeur », et le droit *sui generis* du producteur de base de données
  (art. L342-1 CPI) interdit d'extraire une **partie substantielle** du fonds.

D'où la conception : **on ne rapatrie jamais le catalogue**. Les sitemaps
donnent ~11 000 URL ; on les filtre *localement*, sans rien demander au site, et
on n'ouvre que les pages retenues, dans la limite de `PLAFOND_PAGES` **par
scan** — toutes recherches enregistrées confondues, et non par recherche.

`PLAFOND_PAGES` est une contrainte juridique, pas un réglage de performance.
Ne pas le lever sans le consentement écrit mentionné ci-dessus.

Deux limites de la source, à connaître avant de lire les scores :

- **la localisation manque une fois sur deux** — `pays` est alors une liste
  vide. On rattrape ce qu'on peut depuis l'intitulé, sinon le critère pays
  reste non évaluable (et son poids est redistribué) ;
- **les sitemaps n'ont pas de `lastmod`** : impossible de repérer les
  nouveautés sans ouvrir les pages. C'est la déduplication par `hash` qui fait
  le travail.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from html import unescape

from ..models.enums import PAYS_FILTRES
from .base import BaseConnector, ErreurConnecteur, RawOffer, SearchQuery
from .http import ErreurHttp

log = logging.getLogger("dreamjob.dogfinance")

URL_BASE = "https://dogfinance.com"
URL_SITEMAP_INDEX = f"{URL_BASE}/sitemap-index.xml"

# Plafond de pages d'offres ouvertes par scan. Voir l'en-tête du module : c'est
# ce qui garde le prélèvement en « partie non substantielle ».
PLAFOND_PAGES = 40

_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>', re.S
)
_SAUTS = re.compile(r"(?i)<(?:br|/p|/li|/div|/h[1-6]|/tr)\b[^>]*>")
_BALISES = re.compile(r"<[^>]+>")

# Le site n'expose pas de code ROME, mais `metiers[].nom` joue le même rôle : un
# libellé de famille de métier. On le range sous la clé que le scoring lit déjà
# (`scoring/extraction.py`), plutôt que de toucher au scoring pour une source
# de plus.
CLE_LIBELLE_METIER = "romeLibelle"

_CONTRATS = {
    "CDI": "CDI",
    "CDD": "CDD",
    "STAGE": "Stage",
    "VIE": "V.I.E",
    "VIA": "V.I.E",
    "ALTERNANCE": "Alternance",
    "APPRENTISSAGE": "Alternance",
    "PROFESSIONNALISATION": "Alternance",
    "INTERIM": "Intérim",
    "FREELANCE": "Freelance",
    "INDEPENDANT": "Freelance",
}


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in decompose if not unicodedata.combining(c)).lower()


_PAYS_NORMALISES = {_sans_accents(p): p for p in PAYS_FILTRES}


def _jetons(expression: str) -> list[str]:
    """Mots significatifs d'un mot-clé de recherche.

    Les points sautent avant le découpage : « V.I.E » doit donner « vie », et
    non trois lettres isolées qu'on jetterait aussitôt.
    """
    nu = _sans_accents(expression).replace(".", "")
    return [j for j in re.split(r"[^a-z0-9]+", nu) if len(j) > 2]


class DogFinanceConnector(BaseConnector):
    cle = "dogfinance"
    libelle = "DogFinance"

    def __init__(self, http, reglages) -> None:
        super().__init__(http, reglages)
        # Le plafond se compte **par scan**, pas par recherche : `scan.py`
        # construit un connecteur par source puis lui passe chaque recherche
        # tour à tour. Sans budget porté par l'instance, quatre recherches
        # enregistrées ouvriraient quatre fois quarante pages.
        self._budget = PLAFOND_PAGES
        self._deja_vues: set[str] = set()

    def fetch(self, query: SearchQuery) -> list[RawOffer]:
        urls = self._urls_du_sitemap()
        # Plusieurs recherches ramènent souvent la même annonce : la compter une
        # fois par recherche gâcherait le budget sans rien apporter.
        retenues = [u for u in self._retenir(urls, query) if u not in self._deja_vues]
        plafond = max(0, min(query.max_offres, self._budget))
        retenues = retenues[:plafond]
        self._deja_vues.update(retenues)
        self._budget -= len(retenues)

        log.info("DogFinance : %d URL au sitemap, %d retenues (budget restant %d)",
                 len(urls), len(retenues), self._budget)

        offres: list[RawOffer] = []
        echecs = 0
        for url in retenues:
            try:
                brute = self._lire_offre(url)
            except ErreurHttp as e:
                log.warning("DogFinance : %s illisible (%s)", url, e)
                echecs += 1
                continue
            if brute is None:
                echecs += 1
                continue
            offres.append(self._convertir(brute, url))

        # Toutes les pages illisibles = le site a changé de structure, ce n'est
        # pas un aléa. On veut le voir dans ScanRun plutôt que zéro offre en
        # silence. Quelques échecs isolés, en revanche, sont normaux.
        if retenues and not offres:
            raise ErreurConnecteur(
                f"DogFinance : aucune des {echecs} pages ouvertes n'a pu être lue. "
                "La structure du site a probablement changé — le connecteur est à "
                "reprendre (bloc __NEXT_DATA__, props.initialProps.pageProps.offreSSR)."
            )
        return offres

    # -------------------------------------------------------------- sitemaps

    def _urls_du_sitemap(self) -> list[str]:
        """URL des offres, telles que le site les publie lui-même.

        On repasse par l'index à chaque fois plutôt que de figer les trois
        sitemaps connus : le jour où un quatrième apparaît, on le suit.
        """
        try:
            index = self.http.get(URL_SITEMAP_INDEX)
        except ErreurHttp as e:
            raise ErreurConnecteur(f"Sitemap DogFinance injoignable : {e}") from e

        sitemaps = [u for u in _LOC.findall(index.texte) if "sitemap-offers" in u]
        if not sitemaps:
            raise ErreurConnecteur(
                "L'index des sitemaps DogFinance ne référence plus aucun "
                "« sitemap-offers » : la source a changé d'organisation."
            )

        urls: list[str] = []
        for sitemap in sitemaps:
            try:
                page = self.http.get(sitemap)
            except ErreurHttp as e:
                log.warning("DogFinance : sitemap %s illisible (%s)", sitemap, e)
                continue
            urls.extend(u for u in _LOC.findall(page.texte) if "/offre/" in u)
        return urls

    @staticmethod
    def _retenir(urls: list[str], query: SearchQuery) -> list[str]:
        """Filtre local : aucune requête n'est faite au site pour trier.

        Une URL est retenue si, pour au moins un mot-clé, **tous** ses mots
        significatifs apparaissent dans l'adresse — qui porte l'entreprise et
        l'intitulé. Exiger tous les mots évite de gâcher le plafond sur des
        annonces qui ne partagent qu'un mot passe-partout.
        """
        groupes = [j for j in (_jetons(m) for m in query.mots_cles) if j]
        if not groupes:
            # Sans mot-clé, on ne sait pas trier et le sitemap ne porte pas de
            # date : on prend la tête de liste, faute de mieux. Le scoring fera
            # le tri derrière.
            log.warning("DogFinance : aucun mot-clé exploitable, tri impossible.")
            return urls

        retenues = []
        for url in urls:
            adresse = _sans_accents(url)
            # `rstrip("s")` rattrape les pluriels : « risques » doit rencontrer
            # « analyste-risque-credit ».
            if any(all(j.rstrip("s") in adresse for j in groupe) for groupe in groupes):
                retenues.append(url)
        return retenues

    # --------------------------------------------------------------- lecture

    def _lire_offre(self, url: str) -> dict | None:
        """Objet d'offre embarqué dans la page, ou None si la page n'en a pas."""
        page = self.http.get(url)
        bloc = _NEXT_DATA.search(page.texte)
        if bloc is None:
            log.warning("DogFinance : pas de bloc __NEXT_DATA__ sur %s", url)
            return None
        try:
            donnees = json.loads(bloc.group(1))
        except ValueError as e:
            log.warning("DogFinance : __NEXT_DATA__ illisible sur %s (%s)", url, e)
            return None

        offre = (donnees.get("props", {})
                 .get("initialProps", {})
                 .get("pageProps", {})
                 .get("offreSSR"))
        if not isinstance(offre, dict) or not offre.get("titre"):
            log.warning("DogFinance : offre absente ou vide sur %s", url)
            return None
        return offre

    # ------------------------------------------------------------ conversion

    @staticmethod
    def _texte(html: str) -> str:
        """HTML d'annonce en texte lisible.

        Les fins de bloc deviennent des sauts de ligne : sans cela, les puces
        d'une annonce se recollent en un pavé continu et le scoring y perd les
        limites de phrase.
        """
        sans_puces = _SAUTS.sub("\n", html or "")
        nu = unescape(_BALISES.sub(" ", sans_puces))
        # Les balises retirées laissent des espaces en tête de ligne : on les
        # reprend ligne à ligne plutôt qu'en bloc, sinon les sauts disparaissent.
        lignes = [ligne.strip() for ligne in re.sub(r"[^\S\n]+", " ", nu).splitlines()]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lignes)).strip()

    @staticmethod
    def _noeud(valeur) -> dict:
        """Champ structuré du site : un objet quand il est renseigné, une liste
        vide quand il ne l'est pas. On ramène les deux à un dictionnaire."""
        return valeur if isinstance(valeur, dict) else {}

    @classmethod
    def _pays(cls, brute: dict) -> str:
        structure = cls._noeud(brute.get("pays")).get("nom") or ""
        if structure:
            return _PAYS_NORMALISES.get(_sans_accents(structure), structure)

        # Une offre sur deux n'a pas de pays renseigné alors que son intitulé le
        # nomme (« … - Luxembourg - H/F »). Tout étiqueter « France » fausserait
        # le critère, exactement comme chez France Travail.
        nu = _sans_accents(brute.get("titre") or "")
        for cle, pays in _PAYS_NORMALISES.items():
            if re.search(rf"\b{re.escape(cle)}\b", nu):
                return pays
        return ""

    @classmethod
    def _lieu(cls, brute: dict) -> str:
        ville = brute.get("villeTxt") or cls._noeud(brute.get("ville")).get("nom")
        if ville:
            return ville
        return (cls._noeud(brute.get("departement")).get("nom")
                or cls._noeud(brute.get("region")).get("nom") or "")

    @staticmethod
    def _contrat(brute: dict) -> str:
        """Type de contrat, ou chaîne vide s'il est réellement absent.

        Absent et « inconnu de notre vocabulaire » sont deux cas différents :
        le premier laisse le critère non évaluable, le second vaut « Autre ».
        """
        brut = (brute.get("contrat") or "").strip().upper()
        if not brut:
            return ""
        return _CONTRATS.get(brut, "Autre")

    @staticmethod
    def _date(horodatage) -> datetime | None:
        """`datePub` est un timestamp Unix ; la base stocke de l'UTC naïf."""
        if not horodatage:
            return None
        try:
            instant = datetime.fromtimestamp(int(horodatage), tz=timezone.utc)
        except (TypeError, ValueError, OSError, OverflowError):
            return None
        return instant.replace(tzinfo=None)

    def _convertir(self, brute: dict, url: str) -> RawOffer:
        # Missions et présentation de l'entreprise sont deux champs distincts ;
        # le scoring a besoin des deux pour retrouver les compétences.
        description = "\n\n".join(filter(None, [
            self._texte(brute.get("missions") or ""),
            self._texte(brute.get("descEntreprise") or ""),
        ]))

        metiers = [m.get("nom") for m in (brute.get("metiers") or [])
                   if isinstance(m, dict) and m.get("nom")]
        raw = dict(brute)
        if metiers:
            raw[CLE_LIBELLE_METIER] = " ".join(metiers)

        chemin = brute.get("urlSexy") or ""
        return RawOffer(
            source=self.cle,
            source_id=str(brute.get("id") or ""),
            titre=brute.get("titre") or "",
            url=f"{URL_BASE}{chemin}" if chemin.startswith("/") else (chemin or url),
            entreprise=self._noeud(brute.get("auteur")).get("nom") or "",
            lieu=self._lieu(brute),
            pays=self._pays(brute),
            type_contrat=self._contrat(brute),
            date_publication=self._date(brute.get("datePub")),
            description_brute=description,
            raw=raw,
        )
