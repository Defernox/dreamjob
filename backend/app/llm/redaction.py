"""Choix du rédacteur : Ollama en local (gratuit) ou Anthropic (payant).

Le reste du code ne connaît qu'une fonction `(systeme, message) -> texte`. Le
garde-fou anti-invention est identique dans les deux cas — il porte sur le
résultat, pas sur le fournisseur.

Côté Anthropic, chaque appel relève sa consommation (`AppelAnthropic.consommation`)
et la chiffre : l'utilisateur paie ses générations, il doit pouvoir lire ce que
coûte chaque dossier dans `generation.json`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from ..config import Reglages
from .client import ClientLlm, LlmErreur, LlmIndisponible
from .ollama import ClientOllama, OllamaIndisponible

log = logging.getLogger("dreamjob.redaction")

Redacteur = Callable[[str, str], str]
T = TypeVar("T", bound=BaseModel)

# Multiplicateurs appliqués au tarif d'entrée pour les jetons servis ou écrits
# par le cache de prompt côté Anthropic.
FACTEUR_CACHE_LU = 0.1
FACTEUR_CACHE_ECRIT = 1.25


def etat(reglages: Reglages) -> tuple[bool, str]:
    """(prêt, message). Alimente l'écran de diagnostic, ne lève jamais."""
    if reglages.llm.local:
        return ClientOllama(reglages.llm).disponible()
    if not reglages.llm_disponible:
        return False, "Aucune ANTHROPIC_API_KEY dans .env."
    return True, ""


def cout_usd(modele: str, usage, tarifs: dict[str, tuple[float, float]]) -> float:
    """Ce qu'a coûté un appel, en dollars. Zéro pour un modèle sans tarif connu :
    mieux vaut un coût manquant qu'un coût inventé."""
    if modele not in tarifs or usage is None:
        return 0.0
    entree, sortie = tarifs[modele]
    lu = getattr(usage, "cache_read_input_tokens", 0) or 0
    ecrit = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return (
        (usage.input_tokens or 0) * entree
        + lu * entree * FACTEUR_CACHE_LU
        + ecrit * entree * FACTEUR_CACHE_ECRIT
        + (usage.output_tokens or 0) * sortie
    ) / 1_000_000


def _erreur_lisible(e: Exception) -> LlmErreur:
    """Les pannes qu'on rencontre vraiment, en français ; le reste tel quel."""
    import anthropic

    if isinstance(e, anthropic.AuthenticationError):
        return LlmErreur("Clé ANTHROPIC_API_KEY refusée : vérifiez sa valeur dans .env.")
    if isinstance(e, anthropic.RateLimitError):
        return LlmErreur("Limite de débit atteinte chez Anthropic. Réessayez dans une minute.")
    if isinstance(e, anthropic.APIConnectionError):
        return LlmErreur("Anthropic injoignable : vérifiez la connexion Internet.")
    if isinstance(e, anthropic.APIStatusError):
        corps = getattr(e, "body", None)
        erreur = corps.get("error") if isinstance(corps, dict) else None
        detail = erreur.get("message") if isinstance(erreur, dict) else str(e)
        if "credit balance" in str(detail).lower():
            return LlmErreur(
                "Crédits Anthropic épuisés : rechargez le compte, ou basculez sur "
                "Ollama en local (config.yaml → llm.fournisseur: ollama)."
            )
        return LlmErreur(f"Erreur {e.status_code} de l'API Anthropic : {detail}")
    return LlmErreur(f"Appel à Anthropic impossible : {e}")


class AppelAnthropic:
    """Un modèle, un niveau d'effort, un budget — et le relevé de ce qu'il coûte.

    Appelable comme un `Redacteur` (texte libre, pour la lettre), ou via
    `structure()` pour une réponse validée par un schéma (le CV ciblé).
    """

    def __init__(self, reglages: Reglages, *, etape: str, modele: str,
                 effort: str, max_tokens: int, client: ClientLlm | None = None) -> None:
        self.etape = etape
        self.modele = modele
        self.effort = effort
        self.max_tokens = max_tokens
        self.tarifs = reglages.llm.tarifs
        self.client = client or ClientLlm()
        self.consommation: list[dict] = []

    # ------------------------------------------------------------ relevé

    def _relever(self, reponse) -> None:
        usage = getattr(reponse, "usage", None)
        self.consommation.append({
            "etape": self.etape,
            "modele": self.modele,
            "entree": getattr(usage, "input_tokens", 0) or 0,
            "sortie": getattr(usage, "output_tokens", 0) or 0,
            "cache_lu": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "usd": round(cout_usd(self.modele, usage, self.tarifs), 5),
        })

    def _verifier_fin(self, reponse) -> None:
        """Un refus ou une réponse tronquée n'est pas un texte à livrer."""
        if reponse.stop_reason == "refusal":
            raise LlmErreur(
                f"{self.modele} a décliné la demande ({self.etape}). Réessayez ; si "
                "cela se répète, basculez sur un autre modèle dans config.yaml.")
        if reponse.stop_reason == "max_tokens":
            raise LlmErreur(
                f"Réponse tronquée ({self.etape}) : le budget de {self.max_tokens} jetons "
                "a été atteint. Augmentez-le dans config.yaml.")

    def _parametres(self, systeme: str, message: str) -> dict:
        # Ni `temperature` ni `thinking` : ces modèles refusent le premier, et
        # réfléchissent d'office — l'effort est le seul réglage de profondeur.
        return {
            "model": self.modele,
            "max_tokens": self.max_tokens,
            "system": [{"type": "text", "text": systeme,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": message}],
            "output_config": {"effort": self.effort},
        }

    # ------------------------------------------------------------ appels

    def __call__(self, systeme: str, message: str) -> str:
        """Texte libre, en flux : la réflexion peut prendre du temps, et le flux
        protège des délais de connexion sans rien changer au résultat."""
        try:
            with self.client._anthropic().messages.stream(
                    **self._parametres(systeme, message)) as flux:
                reponse = flux.get_final_message()
        except LlmErreur:
            raise
        except Exception as e:  # noqa: BLE001 — traduit en LlmErreur lisible
            raise _erreur_lisible(e) from e

        self._relever(reponse)
        self._verifier_fin(reponse)
        texte = "".join(b.text for b in reponse.content if b.type == "text").strip()
        if not texte:
            raise LlmErreur(f"{self.modele} a renvoyé une réponse vide ({self.etape}).")
        return texte

    def structure(self, systeme: str, message: str, format_sortie: type[T]) -> T:
        """Réponse contrainte par un schéma et validée par Pydantic."""
        try:
            reponse = self.client._anthropic().messages.parse(
                **self._parametres(systeme, message), output_format=format_sortie)
        except LlmErreur:
            raise
        except Exception as e:  # noqa: BLE001
            raise _erreur_lisible(e) from e

        self._relever(reponse)
        self._verifier_fin(reponse)
        if reponse.parsed_output is None:
            raise LlmErreur(f"{self.modele} n'a pas rendu la structure attendue ({self.etape}).")
        return reponse.parsed_output


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

    log.info("Rédaction : Anthropic %s (effort %s)", reglages.llm.modele_lettre,
             reglages.llm.effort_lettre)
    return AppelAnthropic(reglages, etape="lettre", modele=reglages.llm.modele_lettre,
                          effort=reglages.llm.effort_lettre,
                          max_tokens=reglages.llm.max_tokens_lettre)


def cibleur(reglages: Reglages) -> AppelAnthropic | None:
    """Le modèle qui adapte le CV à l'offre — ou rien.

    Rien en local : une reformulation qui ne doit RIEN ajouter est précisément
    ce qu'un modèle de 7 milliards de paramètres fait mal, et une puce refusée
    par les contrôles retombe de toute façon sur l'originale.
    """
    if reglages.llm.local or not reglages.llm.ciblage_cv or not reglages.llm_disponible:
        return None
    return AppelAnthropic(reglages, etape="ciblage", modele=reglages.llm.modele_ciblage,
                          effort=reglages.llm.effort_ciblage,
                          max_tokens=reglages.llm.max_tokens_ciblage)


__all__ = ["AppelAnthropic", "Redacteur", "cibleur", "cout_usd", "etat", "redacteur",
           "LlmErreur", "LlmIndisponible"]
