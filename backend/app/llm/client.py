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
        return reglages().llm_disponible

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
    ) -> tuple[T, bool]:
        """Renvoie `(resultat_valide, depuis_cache)`.

        `format_sortie` est un modèle Pydantic : l'API contraint sa réponse à ce
        schéma (structured outputs), le SDK la valide. Pas de JSON à rafistoler.
        """
        cle = LlmCache.construire_cle(type_appel, hash_source, modele)

        if not forcer:
            en_cache = self._lire_cache(cle, format_sortie)
            if en_cache is not None:
                log.info("%s : réponse servie depuis le cache", type_appel)
                return en_cache, True

        client = self._anthropic()
        log.info("%s : appel à %s (%d tokens max)", type_appel, modele, max_tokens)

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
        log.info("%s : %d tokens entrée (%d lus en cache), %d sortie",
                 type_appel, u.input_tokens, getattr(u, "cache_read_input_tokens", 0) or 0,
                 u.output_tokens)

        self._ecrire_cache(cle, type_appel, hash_source, modele, resultat)
        return resultat, False
