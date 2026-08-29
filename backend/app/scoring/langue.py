"""Détection de la langue d'une offre — code pur, aucune dépendance.

Méthode : compter les mots-outils propres à chaque langue. Sur un texte d'offre
(quelques centaines de caractères au minimum), c'est fiable et instantané. Une
bibliothèque tierce serait plus précise sur un SMS ; ici elle serait du poids mort.
"""

from __future__ import annotations

from .texte import mots

# Mots-outils discriminants. Volontairement courts : ce sont les mots qu'aucune
# offre ne peut éviter, et qui se recoupent peu d'une langue à l'autre.
MARQUEURS: dict[str, set[str]] = {
    "fr": {"le", "la", "les", "des", "du", "une", "et", "est", "pour", "avec", "dans",
           "vous", "nous", "votre", "notre", "qui", "sont", "sera", "aux", "chez",
           "ainsi", "afin", "cette", "leurs", "plus", "sur"},
    "en": {"the", "of", "and", "to", "for", "with", "you", "your", "we", "our", "is",
           "are", "will", "this", "that", "from", "have", "has", "their", "about",
           "these", "such", "within", "would"},
    "de": {"der", "die", "das", "und", "den", "dem", "ein", "eine", "fur", "mit", "von",
           "zu", "im", "ist", "sind", "sie", "wir", "auch", "nicht", "auf", "bei",
           "unser", "unsere", "werden"},
    "es": {"el", "los", "las", "del", "una", "para", "con", "su", "sus", "que", "se",
           "por", "como", "nuestro", "nuestra", "tus", "sobre", "este", "esta", "sera"},
    "it": {"il", "lo", "gli", "delle", "degli", "una", "per", "con", "che", "non",
           "da", "come", "nostro", "nostra", "questo", "questa", "sara", "sono"},
    "nl": {"het", "een", "van", "voor", "met", "je", "zijn", "te", "op", "dat", "niet",
           "als", "onze", "wij", "wordt", "bij", "aan"},
}

# En dessous, le texte est trop court pour trancher.
MOTS_MINIMUM = 12


def detecter(texte: str | None, *, defaut: str = "") -> str:
    """Code ISO 639-1, ou `defaut` si le texte est trop court ou indécis."""
    jetons = mots(texte, garder_vides=True)
    if len(jetons) < MOTS_MINIMUM:
        return defaut

    comptes = {code: sum(1 for m in jetons if m in marqueurs)
               for code, marqueurs in MARQUEURS.items()}
    meilleure = max(comptes, key=lambda c: comptes[c])
    if comptes[meilleure] == 0:
        return defaut

    # Une langue doit nettement devancer la suivante : sinon on préfère ne rien
    # affirmer plutôt que d'écarter une offre à tort.
    seconde = max((v for c, v in comptes.items() if c != meilleure), default=0)
    if comptes[meilleure] < seconde * 1.3:
        return defaut
    return meilleure
