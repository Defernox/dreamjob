"""Client Ollama — le modèle tourne sur la machine, rien ne sort et rien n'est facturé.

Le serveur Ollama n'est pas démarré en permanence : son absence est une panne
explicable, pas un plantage.
"""

from __future__ import annotations

import json
import logging
import time

import httpx

from ..config import Llm

log = logging.getLogger("dreamjob.ollama")

# Un mur d'horloge est le mauvais outil ici. Mesuré sur une vraie génération :
# le traitement du prompt a mis 271 s, la limite de 300 s a coupé alors qu'il
# restait une trentaine de secondes — 271 secondes de calcul jetées, et aucune
# lettre. On travaille donc en **flux** : ce qu'on surveille est le silence.
#
# `DELAI_SILENCE` borne l'attente ENTRE deux fragments — httpx applique son
# délai `read` à chaque lecture du flux, ce qui est exactement la sémantique
# voulue. Il est large parce que le PREMIER fragment n'arrive qu'une fois tout
# le prompt digéré : c'est la phase qui a mis 271 s le jour de la panne.
DELAI_SILENCE = 420.0
# Garde-fou d'ensemble, vérifié à chaque fragment reçu : un flux qui goutte
# indéfiniment finirait par ne jamais rendre la main.
DELAI_TOTAL = 900.0

# Sans cela, Ollama décharge le modèle après cinq minutes d'inactivité. Entre la
# génération du CV (LibreOffice, une trentaine de secondes) et celle de la
# lettre, le modèle avait le temps de partir : chaque document rechargeait
# 4,4 Go depuis le disque.
DUREE_RESIDENCE = "30m"


class OllamaIndisponible(RuntimeError):
    """Serveur arrêté, ou modèle absent."""


class ClientOllama:
    def __init__(self, reglages: Llm) -> None:
        self.url = reglages.ollama_url.rstrip("/")
        self.modele = reglages.modele_local

    # ------------------------------------------------------------ diagnostic

    def modeles_installes(self) -> list[str]:
        try:
            reponse = httpx.get(f"{self.url}/api/tags", timeout=5.0)
            reponse.raise_for_status()
        except httpx.HTTPError as e:
            raise OllamaIndisponible(
                "Ollama ne répond pas. Démarrez-le (icône dans la barre des tâches, "
                "ou la commande « ollama serve ») puis réessayez."
            ) from e
        return [m["name"] for m in reponse.json().get("models", [])]

    def disponible(self) -> tuple[bool, str]:
        """(prêt, message). Ne lève jamais : sert à l'écran de diagnostic."""
        try:
            installes = self.modeles_installes()
        except OllamaIndisponible as e:
            return False, str(e)

        # « mistral:7b » et « mistral:latest » désignent souvent le même modèle.
        racine = self.modele.split(":")[0]
        if not any(m == self.modele or m.split(":")[0] == racine for m in installes):
            return False, (f"Le modèle « {self.modele} » n'est pas installé. "
                           f"Lancez : ollama pull {self.modele}")
        return True, ""

    # --------------------------------------------------------------- requête

    def extraire_json(self, systeme: str, message: str, schema: dict,
                      *, temperature: float = 0.0) -> str:
        """Réponse contrainte par un schéma JSON.

        Ollama accepte le schéma dans `format` : le modèle ne peut alors
        produire qu'une structure valide, ce qui évite d'avoir à rafistoler du
        JSON approximatif. Température à zéro : structurer un CV n'est pas un
        exercice de création.
        """
        return self._appeler(systeme, message, temperature=temperature, format_=schema)

    def generer(self, systeme: str, message: str, *, temperature: float = 0.3) -> str:
        return self._appeler(systeme, message, temperature=temperature)

    def _appeler(self, systeme: str, message: str, *, temperature: float,
                 format_: dict | None = None) -> str:
        pret, probleme = self.disponible()
        if not pret:
            raise OllamaIndisponible(probleme)

        charge_utile = {
            "model": self.modele,
            "stream": True,
            "keep_alive": DUREE_RESIDENCE,
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": systeme},
                {"role": "user", "content": message},
            ],
        }
        if format_ is not None:
            charge_utile["format"] = format_

        # `read` s'applique à l'attente de CHAQUE fragment, pas à l'appel entier :
        # c'est toute la raison du passage en flux.
        delais = httpx.Timeout(DELAI_SILENCE, connect=5.0, write=30.0)
        debut = time.monotonic()
        morceaux: list[str] = []
        final: dict = {}

        try:
            with httpx.stream("POST", f"{self.url}/api/chat", timeout=delais,
                              json=charge_utile) as reponse:
                reponse.raise_for_status()
                for ligne in reponse.iter_lines():
                    if not ligne:
                        continue
                    fragment = json.loads(ligne)
                    if fragment.get("error"):
                        raise OllamaIndisponible(f"Ollama a échoué : {fragment['error']}")
                    morceaux.append((fragment.get("message") or {}).get("content", ""))
                    if fragment.get("done"):
                        final = fragment
                        break
                    if time.monotonic() - debut > DELAI_TOTAL:
                        raise OllamaIndisponible(
                            f"Ollama produit trop lentement : {len(morceaux)} fragments "
                            f"en {DELAI_TOTAL:.0f} s. La carte graphique est saturée.")
        except httpx.ReadTimeout as e:
            raise OllamaIndisponible(self._diagnostic_lenteur(len(morceaux), debut)) from e
        except httpx.HTTPError as e:
            raise OllamaIndisponible(f"Ollama a échoué : {e}") from e

        texte = "".join(morceaux).strip()
        if not texte:
            raise OllamaIndisponible("Ollama a renvoyé une réponse vide.")

        prompt_ns = final.get("prompt_eval_duration") or 0
        sortie_ns = final.get("eval_duration") or 1
        log.info("Ollama %s : prompt %d jetons en %.1f s, sortie %d jetons en %.1f s "
                 "(%.0f j/s), total %.1f s", self.modele,
                 final.get("prompt_eval_count", 0), prompt_ns / 1e9,
                 final.get("eval_count", 0), sortie_ns / 1e9,
                 (final.get("eval_count", 0)) / (sortie_ns / 1e9),
                 time.monotonic() - debut)
        return texte

    def _diagnostic_lenteur(self, recus: int, debut: float) -> str:
        """Nommer la vraie cause plutôt que de répéter « timed out ».

        Le message a compté : « Ollama a échoué : timed out » n'apprend rien.
        La panne observée est une saturation de la mémoire vidéo — mistral:7b
        réclame ~5,1 Go quand une carte de 6 Go n'en offre que 4,6 de libres.
        Windows migre alors silencieusement la mémoire GPU vers la RAM, et le
        débit s'effondre d'un facteur cent, par à-coups.
        """
        ecoule = time.monotonic() - debut
        if recus == 0:
            return (f"Ollama n'a rien renvoyé en {ecoule:.0f} s. Le modèle "
                    f"« {self.modele} » ne tient probablement pas entièrement dans la "
                    "mémoire de la carte graphique : fermez le navigateur et les autres "
                    "applications, ou choisissez un modèle plus léger dans "
                    "config.yaml → llm.modele_local.")
        return (f"Ollama s'est interrompu après {ecoule:.0f} s et {recus} fragments. "
                "La carte graphique est probablement saturée par une autre application.")
