"""Choix du rédacteur : Ollama en local (gratuit) ou Anthropic (payant).

Le reste du code ne connaît qu'une fonction `(systeme, message) -> texte`. Le
garde-fou anti-invention est identique dans les deux cas — il porte sur le
résultat, pas sur le fournisseur.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from ..config import Reglages
from .client import ClientLlm, LlmErreur, LlmIndisponible
from .ollama import ClientOllama, OllamaIndisponible

log = logging.getLogger("dreamjob.redaction")

Redacteur = Callable[[str, str], str]


def etat(reglages: Reglages) -> tuple[bool, str]:
    """(prêt, message). Alimente l'écran de diagnostic, ne lève jamais."""
    if reglages.llm.local:
        return ClientOllama(reglages.llm).disponible()
    if not reglages.llm_disponible:
        return False, "Aucune ANTHROPIC_API_KEY dans .env."
    return True, ""


def redacteur(reglages: Reglages) -> Redacteur:
    if reglages.llm.local:
        client = ClientOllama(reglages.llm)
        log.info("Rédaction : Ollama %s (local, gratuit)", reglages.llm.modele_local)

        def generer_local(systeme: str, message: str) -> str:
            try:
                return client.generer(systeme, message)
            except OllamaIndisponible as e:
                raise LlmErreur(str(e)) from e

        return generer_local

    client = ClientLlm()
    log.info("Rédaction : Anthropic %s", reglages.llm.modele_redaction)

    def generer_distant(systeme: str, message: str) -> str:
        import anthropic

        try:
            reponse = client._anthropic().messages.create(
                model=reglages.llm.modele_redaction,
                max_tokens=reglages.llm.max_tokens_lettre,
                system=[{"type": "text", "text": systeme,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": message}],
            )
        except anthropic.APIStatusError as e:
            corps = getattr(e, "body", None)
            erreur = corps.get("error") if isinstance(corps, dict) else None
            detail = erreur.get("message") if isinstance(erreur, dict) else str(e)
            if "credit balance" in str(detail).lower():
                raise LlmErreur(
                    "Crédits Anthropic épuisés. Basculez sur Ollama en local : "
                    "config.yaml → llm.fournisseur: ollama"
                ) from e
            raise LlmErreur(f"Erreur {e.status_code} de l'API Anthropic : {detail}") from e

        return "".join(b.text for b in reponse.content if b.type == "text").strip()

    return generer_distant


__all__ = ["Redacteur", "etat", "redacteur", "LlmErreur", "LlmIndisponible"]
