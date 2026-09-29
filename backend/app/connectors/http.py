"""Client HTTP partagé par tous les connecteurs.

Quatre garanties, imposées ici pour ne pas dépendre de la discipline de chaque
connecteur :

1. **1 requête/seconde par hôte** — on n'assomme aucune source.
2. **User-Agent explicite** — la source sait qui l'appelle et peut nous joindre.
3. **Backoff exponentiel** sur 429 et 5xx, en respectant `Retry-After`.
4. **Cache disque** — relancer un scan dans la foulée ne refait pas les requêtes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

log = logging.getLogger("dreamjob.http")

STATUTS_A_REESSAYER = {408, 425, 429, 500, 502, 503, 504}


def purger_cache(dossier: Path, ttl_secondes: float) -> int:
    """Supprime les réponses mises en cache et périmées. Renvoie leur nombre.

    Une réponse périmée n'est plus jamais lue, mais restait sur le disque : 91 Mo
    en local après quelques semaines d'usage intermittent. Sur un serveur qui
    veille toute la journée — cent cinquante sites d'employeurs toutes les
    demi-heures —, le dossier aurait grossi sans fin."""
    if not dossier.is_dir():
        return 0
    limite = time.time() - ttl_secondes
    retirees = 0
    for fichier in dossier.glob("*.json"):
        try:
            if fichier.stat().st_mtime < limite:
                fichier.unlink()
                retirees += 1
        except OSError:
            continue                # lu ou retiré par un autre au même moment
    return retirees


@dataclass
class Reponse:
    statut: int
    json_: dict | list | None
    texte: str
    entetes: dict
    depuis_cache: bool = False


class ErreurHttp(RuntimeError):
    def __init__(self, statut: int, message: str) -> None:
        super().__init__(message)
        self.statut = statut


# Les validateurs (ETag, Last-Modified) des pages revalidables, avec leur corps :
# pour toute la durée du processus, pas d'un seul scan — la veille crée un
# client par passe, toutes les demi-heures. Borné par la taille des corps, pas
# par leur nombre, et la page la moins récemment relue part d'abord : une
# borne à 300 pages, vidée dans l'ordre d'arrivée, était dépassée à chaque
# passe (plans et listes de 158 employeurs) et chaque page en chassait une
# autre avant d'avoir resservi — plus aucun 304.
_VALIDATIONS: OrderedDict[str, tuple[dict[str, str], Reponse]] = OrderedDict()
_VERROU_VALIDATIONS = threading.Lock()
VALIDATIONS_OCTETS_MAX = 96 * 1024 * 1024
_validations_octets = 0


def _poids(reponse: Reponse) -> int:
    return len(reponse.texte or "")


def oublier_validations() -> None:
    """Vide la mémoire des validateurs (tests)."""
    global _validations_octets
    with _VERROU_VALIDATIONS:
        _VALIDATIONS.clear()
        _validations_octets = 0


class ClientHttp:
    def __init__(
        self,
        *,
        user_agent: str,
        requetes_par_seconde: float = 1.0,
        timeout: int = 20,
        tentatives_max: int = 4,
        dossier_cache: Path | None = None,
        cache_ttl_heures: int = 12,
    ) -> None:
        self.user_agent = user_agent
        # 0 = limiteur désactivé (tests, ou source qui l'autorise explicitement).
        self.intervalle = 1.0 / requetes_par_seconde if requetes_par_seconde > 0 else 0.0
        self.timeout = timeout
        self.tentatives_max = tentatives_max
        self.dossier_cache = dossier_cache
        self.cache_ttl = cache_ttl_heures * 3600
        self._dernier_appel: dict[str, float] = {}
        # Les sites des employeurs sont interrogés en parallèle, un fil par
        # site : le tour de parole se prend donc sous verrou, un par hôte, pour
        # que deux fils ne tombent jamais sur le même serveur dans la seconde.
        self._verrou = threading.Lock()
        self._verrous_hotes: dict[str, threading.Lock] = {}
        # Un site peut demander plus lent (`Crawl-delay` de robots.txt) : le
        # délai par hôte l'emporte alors sur l'intervalle commun.
        self._intervalles: dict[str, float] = {}
        # Créé à la première requête : monter un contexte SSL coûte ~1 s, inutile
        # pour un scan dont toutes les réponses sortent du cache.
        self._client: httpx.Client | None = None

    def _session(self) -> httpx.Client:
        with self._verrou:
            if self._client is None:
                self._client = httpx.Client(timeout=self.timeout, follow_redirects=True)
            return self._client

    def fermer(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> ClientHttp:
        return self

    def __exit__(self, *_) -> None:
        self.fermer()

    # ------------------------------------------------------------ limitation

    def _attendre_son_tour(self, url: str) -> None:
        hote = urlparse(url).netloc.lower()
        with self._verrou:
            verrou = self._verrous_hotes.setdefault(hote, threading.Lock())
        with verrou:
            precedent = self._dernier_appel.get(hote)
            if precedent is not None:
                intervalle = max(self.intervalle, self._intervalles.get(hote, 0.0))
                reste = intervalle - (time.monotonic() - precedent)
                if reste > 0:
                    time.sleep(reste)
            self._dernier_appel[hote] = time.monotonic()

    def ralentir(self, hote: str, secondes: float) -> None:
        """Au moins `secondes` entre deux requêtes vers cet hôte — jamais moins
        que l'intervalle commun. Plafonné à une minute : au-delà, c'est une
        valeur aberrante, pas une demande de politesse."""
        with self._verrou:
            self._intervalles[hote.lower()] = min(max(secondes, 0.0), 60.0)

    # ----------------------------------------------------------------- cache

    def _chemin_cache(self, methode: str, url: str, params: dict | None,
                      donnees: dict | None, corps_json: dict | None) -> Path | None:
        if self.dossier_cache is None:
            return None
        empreinte = hashlib.sha256(
            json.dumps([methode, url, params or {}, donnees or {}, corps_json or {}],
                       sort_keys=True).encode()
        ).hexdigest()
        return self.dossier_cache / f"{empreinte}.json"

    def _lire_cache(self, chemin: Path | None) -> Reponse | None:
        if chemin is None or not chemin.exists():
            return None
        if time.time() - chemin.stat().st_mtime > self.cache_ttl:
            return None
        try:
            donnees = json.loads(chemin.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return Reponse(donnees["statut"], donnees["json"], donnees["texte"],
                       donnees["entetes"], depuis_cache=True)

    def _ecrire_cache(self, chemin: Path | None, reponse: Reponse) -> None:
        if chemin is None or reponse.statut >= 400:
            return
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps({
            "statut": reponse.statut, "json": reponse.json_,
            "texte": reponse.texte, "entetes": reponse.entetes,
        }, ensure_ascii=False), encoding="utf-8")

    # ---------------------------------------------------------------- requête

    def requete(
        self,
        methode: str,
        url: str,
        *,
        params: dict | None = None,
        donnees: dict | None = None,      # corps de formulaire (OAuth notamment)
        corps_json: dict | None = None,   # corps JSON (APIs modernes)
        entetes: dict | None = None,
        utiliser_cache: bool = True,
        statuts_acceptes: tuple[int, ...] = (200,),
        revalider: bool = False,
    ) -> Reponse:
        """`revalider` : une page relue souvent et qui change peu (le plan du
        site d'un employeur, toutes les demi-heures en veille) est redemandée
        sous condition — « If-None-Match », « If-Modified-Since ». Un site qui
        répond 304 ne renvoie rien : Hays économise ainsi 2 Mo par passe."""
        chemin = (self._chemin_cache(methode, url, params, donnees, corps_json)
                  if utiliser_cache else None)
        en_cache = self._lire_cache(chemin)
        if en_cache is not None:
            log.debug("cache : %s %s", methode, url)
            return en_cache

        tous_entetes = {"User-Agent": self.user_agent, **(entetes or {})}
        connue = None
        if revalider and methode == "GET" and not params:
            with _VERROU_VALIDATIONS:
                connue = _VALIDATIONS.get(url)
                if connue is not None:
                    _VALIDATIONS.move_to_end(url)        # relue : la plus récente
            if connue is not None:
                tous_entetes.update(connue[0])
        derniere_erreur: Exception | None = None

        for tentative in range(1, self.tentatives_max + 1):
            self._attendre_son_tour(url)
            try:
                brute = self._session().request(
                    methode, url, params=params, data=donnees, json=corps_json,
                    headers=tous_entetes,
                )
            except httpx.HTTPError as e:
                derniere_erreur = e
                log.warning("%s %s : %s (tentative %d/%d)", methode, url, e,
                            tentative, self.tentatives_max)
                self._patienter(tentative)
                continue

            if brute.status_code in STATUTS_A_REESSAYER and tentative < self.tentatives_max:
                log.warning("%s %s : HTTP %d, nouvelle tentative (%d/%d)", methode, url,
                            brute.status_code, tentative, self.tentatives_max)
                self._patienter(tentative, brute.headers.get("Retry-After"))
                continue

            if brute.status_code == 304 and connue is not None:
                log.debug("inchangé (304) : %s", url)
                return connue[1]

            reponse = Reponse(
                statut=brute.status_code,
                json_=self._json_ou_none(brute),
                texte=brute.text,
                entetes=dict(brute.headers),
            )
            if reponse.statut not in statuts_acceptes:
                raise ErreurHttp(reponse.statut, f"HTTP {reponse.statut} sur {url} : {brute.text[:200]}")
            self._ecrire_cache(chemin, reponse)
            if revalider and methode == "GET" and not params and reponse.statut == 200:
                self._retenir(url, reponse)
            return reponse

        raise ErreurHttp(0, f"{url} injoignable après {self.tentatives_max} tentatives "
                            f"({derniere_erreur})")

    def get(self, url: str, **kw) -> Reponse:
        return self.requete("GET", url, **kw)

    def post(self, url: str, **kw) -> Reponse:
        return self.requete("POST", url, **kw)

    # ------------------------------------------------------------------ outils

    @staticmethod
    def _retenir(url: str, reponse: Reponse) -> None:
        """Garde les validateurs d'une réponse revalidable, s'il y en a."""
        global _validations_octets
        entetes = {k.lower(): v for k, v in reponse.entetes.items()}
        validateurs = {}
        if etag := entetes.get("etag"):
            validateurs["If-None-Match"] = etag
        if modifie := entetes.get("last-modified"):
            validateurs["If-Modified-Since"] = modifie
        with _VERROU_VALIDATIONS:
            if (ancienne := _VALIDATIONS.pop(url, None)) is not None:
                _validations_octets -= _poids(ancienne[1])
            if not validateurs or _poids(reponse) > VALIDATIONS_OCTETS_MAX:
                return
            _VALIDATIONS[url] = (validateurs, reponse)
            _validations_octets += _poids(reponse)
            while _validations_octets > VALIDATIONS_OCTETS_MAX:
                _, (_, chassee) = _VALIDATIONS.popitem(last=False)   # la moins récemment relue
                _validations_octets -= _poids(chassee)

    def _patienter(self, tentative: int, retry_after: str | None = None) -> None:
        """Backoff exponentiel avec bruit, sauf si le serveur a dit quand revenir."""
        if retry_after:
            try:
                time.sleep(min(float(retry_after), 60.0))
                return
            except ValueError:
                pass
        time.sleep(min(2 ** (tentative - 1), 30) + random.uniform(0, 0.5))

    @staticmethod
    def _json_ou_none(brute: httpx.Response) -> dict | list | None:
        if not brute.content:
            return None
        try:
            return brute.json()
        except (json.JSONDecodeError, ValueError):
            return None
