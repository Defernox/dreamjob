"""Normalisation de texte, partagée par tout le scoring.

Tout passe par ici : deux textes comparés doivent l'avoir été de la même façon,
sinon les scores deviennent incomparables entre eux.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

_NON_ALPHANUM = re.compile(r"[^a-z0-9+#.]+")
_ESPACES = re.compile(r"\s+")

# Mots trop fréquents pour porter du sens dans une offre d'emploi.
VIDES = {
    "le", "la", "les", "de", "des", "du", "un", "une", "et", "est", "pour", "avec",
    "dans", "sur", "au", "aux", "vous", "nous", "par", "plus", "ce", "cette", "votre",
    "notre", "qui", "que", "sont", "etre", "avoir", "en", "ne", "pas", "ou", "a", "il",
    "elle", "son", "ses", "leur", "leurs", "se", "sa", "y", "d", "l", "s", "n", "the",
    "of", "and", "to", "in", "for", "with", "you", "your", "we", "our", "is", "are",
    "be", "will", "this", "that", "on", "at", "as", "from", "by", "have", "has", "not",
    "poste", "profil", "mission", "missions", "entreprise", "societe", "equipe",
    "recherche", "recherchons", "candidat", "candidate", "offre", "emploi", "travail",
    "experience", "competences", "h", "f", "hf",
}


@lru_cache(maxsize=4096)
def normaliser(texte: str | None) -> str:
    """Minuscules, sans accents, ponctuation réduite à des espaces.

    `+`, `#` et `.` survivent : ils portent du sens dans les noms techniques
    (C++, C#, node.js, bac+5).
    """
    if not texte:
        return ""
    decompose = unicodedata.normalize("NFKD", texte)
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return _ESPACES.sub(" ", _NON_ALPHANUM.sub(" ", sans_accents.lower())).strip()


def mots(texte: str | None, *, garder_vides: bool = False) -> list[str]:
    """Jetons du texte.

    Le point est retiré aux extrémités (« encours. » et « encours » doivent être
    le même mot) mais conservé à l'intérieur (node.js). `+` et `#` ne sont
    retirés qu'au début : en fin de mot ils font partie du nom (c++, c#, f#).
    """
    normalise = normaliser(texte)
    if not normalise:
        return []
    decoupe = [m.strip(".").lstrip("+#") for m in normalise.split()]
    if garder_vides:
        return [m for m in decoupe if m]
    return [m for m in decoupe if m and m not in VIDES and len(m) > 1]


def ensemble_mots(texte: str | None) -> set[str]:
    return set(mots(texte))


# Mots qui structurent un intitulé de compétence sans en porter le sens :
# dans « gestion de trésorerie », c'est « trésorerie » qui compte. Ils gardent un
# poids résiduel — les ignorer tout à fait rendrait « analyse » et « conseil »
# interchangeables.
GENERIQUES = {
    "gestion", "management", "analyse", "analyste", "suivi", "conseil", "conseiller",
    "charge", "chargee", "responsable", "assistant", "assistante", "gestionnaire",
    "maitrise", "connaissance", "connaissances", "pratique", "outils", "outil",
    "technique", "techniques", "methode", "methodes", "projet", "projets",
    "developpement", "support", "service", "services", "operations", "operationnel",
}
POIDS_GENERIQUE = 0.4


def poids_jeton(jeton: str) -> float:
    """Un mot générique pèse moins qu'un mot spécifique dans une compétence."""
    return POIDS_GENERIQUE if jeton in GENERIQUES else 1.0
