"""Client Anthropic + cache en base.

Deux principes, valables pour tout l'appli :

1. **Rien ne s'appelle deux fois.** Chaque réponse est écrite dans `llm_cache`,
   la clé dérivant du hash de la source, du type d'appel et du modèle. Relancer
   un scan, réimporter le même CV : zéro requête, zéro euro.
2. **L'absence de clé n'est pas une panne.** `disponible` est False, l'appelant
   choisit sa dégradation. Rien ne plante au démarrage.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TypeVar

import anthropic
from pydantic import BaseModel
from sqlmodel import Session

from ..config import reglages
from ..models import LlmCache

log = logging.getLogger("dreamjob.llm")

T = TypeVar("T", bound=BaseModel)


class LlmIndisponible(RuntimeError):
    """Pas de clé API : l'appelant doit se rabattre sur le mode dégradé."""


class LlmErreur(RuntimeError):
    """L'appel a échoué. Le message est destiné à l'utilisateur, en français."""


def empreinte(texte: str) -> str:
    """Hash d'un contenu source, utilisé comme clé de cache."""
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


class ClientLlm:
    def __init__(self, session: Session | None = None) -> None:
        self.session = session
        self._client: anthropic.Anthropic | None = None

    @property
    def disponible(self) -> bool:
        """Un fournisseur est-il utilisable ?

        En local, la question n'est pas « y a-t-il une clé » : Ollama vérifie
        lui-même sa disponibilité au moment de l'appel, avec un message précis
        (serveur arrêté, modèle absent). Juger sur ANTHROPIC_API_KEY afficherait
        « mode dégradé » alors que tout fonctionne.
        """
        return True if reglages().llm.local else reglages().llm_disponible

    def _anthropic(self) -> anthropic.Anthropic:
        if not self.disponible:
            raise LlmIndisponible(
                "Aucune ANTHROPIC_API_KEY dans .env : cette fonction a besoin du LLM."
            )
        if self._client is None:
            # La clé est lue dans l'environnement par le SDK : jamais en dur.
            entetes = {}
            workspace = reglages().secret("ANTHROPIC_WORKSPACE_ID")
            if workspace:
                # Requis par les clés liées à une identité (« identity-linked »).
                entetes["anthropic-workspace-id"] = workspace
            self._client = anthropic.Anthropic(
                timeout=180.0, max_retries=3, default_headers=entetes or None
            )
        return self._client

    # ------------------------------------------------------------------ cache

    def _lire_cache(self, cle: str, format_sortie: type[T]) -> T | None:
        if self.session is None:
            return None
        entree = self.session.get(LlmCache, cle)
        if entree is None:
            return None
        try:
            return format_sortie.model_validate(entree.payload)
        except Exception:
            # Le schéma a changé depuis la mise en cache : on ignore l'entrée.
            log.info("Entrée de cache obsolète, ignorée (%s…)", cle[:12])
            return None

    def _ecrire_cache(self, cle: str, type_appel: str, hash_source: str,
                      modele: str, resultat: BaseModel) -> None:
        if self.session is None:
            return
        self.session.merge(LlmCache(
            cle=cle,
            type=type_appel,
            hash_source=hash_source,
            modele=modele,
            payload=resultat.model_dump(mode="json"),
        ))
        self.session.commit()

    # ------------------------------------------------------------------ appel

    def _extraire_en_local(self, systeme: str, message: str,
                           format_sortie: type[T]) -> T:
        from .ollama import ClientOllama, OllamaIndisponible

        client = ClientOllama(reglages().llm)
        try:
            brut = client.extraire_json(systeme, message, format_sortie.model_json_schema())
        except OllamaIndisponible as e:
            raise LlmErreur(str(e)) from e

        try:
            return format_sortie.model_validate_json(brut)
        except Exception as e:  # noqa: BLE001 — un modèle local peut dévier du schéma
            raise LlmErreur(
                f"Le modèle local a renvoyé une structure inexploitable : {e}. "
                f"Essayez un modèle plus capable (config.yaml → llm.modele_local)."
            ) from e

    def _appeler_fournisseur(self, systeme: str, message: str, format_sortie: type[T],
                             modele: str, max_tokens: int) -> T:
        """**Le seul point où l'on choisit un fournisseur.**

        Tout le reste — cache, validation Pydantic, messages d'erreur — est
        commun. Sans cet aiguillage unique, l'import de CV etait reste cable sur
        Anthropic alors que la lettre, elle, savait deja tourner en local.
        """
        if reglages().llm.local:
            return self._extraire_en_local(systeme, message, format_sortie)
        return self._extraire_chez_anthropic(systeme, message, format_sortie,
                                             modele, max_tokens)

    def _extraire_chez_anthropic(self, systeme: str, message: str, format_sortie: type[T],
                                 modele: str, max_tokens: int) -> T:
        client = self._anthropic()
        log.info("Appel à %s (%d tokens max)", modele, max_tokens)

        try:
            reponse = client.messages.parse(
                model=modele,
                max_tokens=max_tokens,
                # Le prompt système est stable d'un appel à l'autre : on le met
                # en cache côté API, ce qui allège chaque requête suivante.
                system=[{"type": "text", "text": systeme,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": message}],
                output_format=format_sortie,
            )
        except anthropic.AuthenticationError as e:
            raise LlmErreur("Clé ANTHROPIC_API_KEY refusée : vérifiez sa validité dans .env.") from e
        except anthropic.RateLimitError as e:
            raise LlmErreur("Limite de débit atteinte chez Anthropic. Réessayez dans une minute.") from e
        except anthropic.APIStatusError as e:
            # Le message d'Anthropic est plus utile qu'une reformulation : on le
            # remonte tel quel, précédé d'une explication en français pour les
            # deux causes qu'on rencontre vraiment.
            corps = getattr(e, "body", None)
            erreur = corps.get("error") if isinstance(corps, dict) else None
            detail = erreur.get("message") if isinstance(erreur, dict) else None
            brut = detail or str(e)

            if "credit balance" in brut.lower():
                raise LlmErreur(
                    "Crédits Anthropic épuisés : achetez des crédits sur "
                    "platform.claude.com (Plans & Billing) pour utiliser l'import de CV, "
                    "le scoring des offres et la génération de lettres. "
                    f"Message d'origine : {brut}"
                ) from e
            if "workspace-id" in brut.lower():
                raise LlmErreur(
                    "Votre clé API est liée à une identité : renseignez "
                    "ANTHROPIC_WORKSPACE_ID dans .env. "
                    f"Message d'origine : {brut}"
                ) from e

            raise LlmErreur(f"Erreur {e.status_code} de l'API Anthropic : {brut}") from e
        except anthropic.APIConnectionError as e:
            raise LlmErreur("Impossible de joindre l'API Anthropic. Vérifiez la connexion.") from e

        resultat = reponse.parsed_output
        if resultat is None:
            raise LlmErreur("Le modèle n'a pas renvoyé de réponse exploitable.")

        u = reponse.usage
        log.info("%d tokens entrée (%d lus en cache), %d sortie",
                 u.input_tokens, getattr(u, "cache_read_input_tokens", 0) or 0,
                 u.output_tokens)
        return resultat

    def extraire(
        self,
        *,
        type_appel: str,
        hash_source: str,
        systeme: str,
        message: str,
        format_sortie: type[T],
        modele: str,
        max_tokens: int,
        forcer: bool = False,
        variante: str = "",
    ) -> tuple[T, bool]:
        """Renvoie `(resultat_valide, depuis_cache)`.

        `format_sortie` est un modèle Pydantic : l'API contraint sa réponse à ce
        schéma (structured outputs), le SDK la valide. Pas de JSON à rafistoler.
        """
        # `variante` distingue plusieurs appels portant sur la même source :
        # les quatre passes d'un import de CV écraseraient sinon la même entrée.
        cle = LlmCache.construire_cle(type_appel, hash_source, modele, variante)

        if not forcer:
            en_cache = self._lire_cache(cle, format_sortie)
            if en_cache is not None:
                log.info("%s : réponse servie depuis le cache", type_appel)
                return en_cache, True

        resultat = self._appeler_fournisseur(
            systeme, message, format_sortie, modele, max_tokens
        )
        self._ecrire_cache(cle, type_appel, hash_source, modele, resultat)
        return resultat, False
