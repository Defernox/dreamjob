"""Client Ollama — le modèle tourne sur la machine, rien ne sort et rien n'est facturé.

Le serveur Ollama n'est pas démarré en permanence : son absence est une panne
explicable, pas un plantage.
"""

from __future__ import annotations

import logging

import httpx

from ..config import Llm

log = logging.getLogger("dreamjob.ollama")

DELAI = 300.0    # un modèle 7B sur GPU met quelques dizaines de secondes


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
            "stream": False,
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": systeme},
                {"role": "user", "content": message},
            ],
        }
        if format_ is not None:
            charge_utile["format"] = format_

        try:
            reponse = httpx.post(f"{self.url}/api/chat", timeout=DELAI, json=charge_utile)
            reponse.raise_for_status()
        except httpx.HTTPError as e:
            raise OllamaIndisponible(f"Ollama a échoué : {e}") from e

        charge = reponse.json()
        texte = (charge.get("message") or {}).get("content", "").strip()
        if not texte:
            raise OllamaIndisponible("Ollama a renvoyé une réponse vide.")

        duree = charge.get("eval_duration") or 1
        log.info("Ollama %s : %d tokens en %.1f s", self.modele,
                 charge.get("eval_count", 0), duree / 1e9)
        return texte
