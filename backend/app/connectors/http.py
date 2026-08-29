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
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

log = logging.getLogger("dreamjob.http")

STATUTS_A_REESSAYER = {408, 425, 429, 500, 502, 503, 504}


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
        # Créé à la première requête : monter un contexte SSL coûte ~1 s, inutile
        # pour un scan dont toutes les réponses sortent du cache.
        self._client: httpx.Client | None = None

    def _session(self) -> httpx.Client:
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
        hote = urlparse(url).netloc
        precedent = self._dernier_appel.get(hote)
        if precedent is not None:
            reste = self.intervalle - (time.monotonic() - precedent)
            if reste > 0:
                time.sleep(reste)
        self._dernier_appel[hote] = time.monotonic()

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
    ) -> Reponse:
        chemin = (self._chemin_cache(methode, url, params, donnees, corps_json)
                  if utiliser_cache else None)
        en_cache = self._lire_cache(chemin)
        if en_cache is not None:
            log.debug("cache : %s %s", methode, url)
            return en_cache

        tous_entetes = {"User-Agent": self.user_agent, **(entetes or {})}
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

            reponse = Reponse(
                statut=brute.status_code,
                json_=self._json_ou_none(brute),
                texte=brute.text,
                entetes=dict(brute.headers),
            )
            if reponse.statut not in statuts_acceptes:
                raise ErreurHttp(reponse.statut, f"HTTP {reponse.statut} sur {url} : {brute.text[:200]}")
            self._ecrire_cache(chemin, reponse)
            return reponse

        raise ErreurHttp(0, f"{url} injoignable après {self.tentatives_max} tentatives "
                            f"({derniere_erreur})")

    def get(self, url: str, **kw) -> Reponse:
        return self.requete("GET", url, **kw)

    def post(self, url: str, **kw) -> Reponse:
        return self.requete("POST", url, **kw)

    # ------------------------------------------------------------------ outils

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
