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


# --- Langues EXIGÉES par l'annonce -------------------------------------------
# Détecter la langue de rédaction ne suffit pas : une offre en français qui
# réclame « anglais courant » est hors de portée sans anglais, alors que le
# critère la donnait pour parfaitement accessible.

_NOMS_LANGUES: dict[str, tuple[str, ...]] = {
    "en": ("anglais", "english"),
    "de": ("allemand", "german", "deutsch"),
    "es": ("espagnol", "spanish"),
    "it": ("italien", "italian"),
    "nl": ("neerlandais", "dutch"),
    "fr": ("francais", "french"),
}

# Mots qui, à proximité d'un nom de langue, en font une exigence et non une
# simple mention (« équipe internationale, anglais et espagnol parlés »).
_MARQUEURS_EXIGENCE = (
    "courant", "couramment", "bilingue", "obligatoire", "exige", "exigee", "requis",
    "requise", "maitrise", "indispensable", "necessaire", "imperatif", "fluent",
    "required", "mandatory", "proficiency", "professionnel", "operationnel", "c1", "c2", "b2",
)

# Fenêtre de mots autour du nom de langue où l'on cherche ces marqueurs.
_FENETRE = 6


def langues_exigees(texte: str | None) -> list[str]:
    """Codes ISO des langues que l'annonce réclame explicitement.

    Une langue seulement citée, sans marqueur d'exigence à proximité, n'est pas
    retenue : mieux vaut manquer une exigence que d'écarter une offre à tort.
    """
    jetons = mots(texte, garder_vides=True)
    if not jetons:
        return []

    exigees: list[str] = []
    for position, jeton in enumerate(jetons):
        for code, noms in _NOMS_LANGUES.items():
            if jeton not in noms or code in exigees:
                continue
            debut = max(0, position - _FENETRE)
            voisinage = jetons[debut:position + _FENETRE + 1]
            if any(v in _MARQUEURS_EXIGENCE for v in voisinage):
                exigees.append(code)
    return exigees
