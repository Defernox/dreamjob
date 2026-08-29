"""Déduplication des offres.

Deux filets, pour deux problèmes différents :

- `(source, source_id)` — contrainte SQL : relancer le même scan ne recrée rien.
- `hash` — calculé ici : la même annonce republiée par une autre source est
  reconnue comme un doublon.

Le hash doit être **stable** (même annonce = même hash, malgré les variations de
casse, d'accents, d'espaces ou de ponctuation) et **discriminant** (deux postes
différents chez le même employeur ne doivent pas se confondre).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

# Seul le début de la description entre dans le hash : les sites ajoutent
# souvent leurs propres mentions légales à la fin.
LONGUEUR_DESCRIPTION = 500

_NON_ALPHANUM = re.compile(r"[^a-z0-9]+")


def normaliser(texte: str | None) -> str:
    """Minuscules, sans accents, sans ponctuation, espaces réduits."""
    if not texte:
        return ""
    decompose = unicodedata.normalize("NFKD", texte)
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return _NON_ALPHANUM.sub(" ", sans_accents.lower()).strip()


def calculer_hash(
    titre: str | None,
    entreprise: str | None,
    lieu: str | None,
    description: str | None,
) -> str:
    """Empreinte d'une annonce, indépendante de la source qui la publie."""
    morceaux = [
        normaliser(titre),
        normaliser(entreprise),
        normaliser(lieu),
        normaliser(description)[:LONGUEUR_DESCRIPTION],
    ]
    return hashlib.sha256("|".join(morceaux).encode("utf-8")).hexdigest()


def hash_offre(offre) -> str:
    """Raccourci pour un RawOffer ou un Offer."""
    return calculer_hash(
        offre.titre, offre.entreprise, offre.lieu, offre.description_brute
    )
