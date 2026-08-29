"""Le code ROME comme signal de secteur — gratuit et déjà dans l'offre.

France Travail classe chaque offre selon le répertoire ROME. La **lettre**
initiale désigne le grand domaine, et c'est le seul niveau retenu ici : les
sous-domaines sont nombreux et évoluent, alors que ces quatorze familles sont
stables. Pour le détail, on se repose sur `romeLibelle`, que l'API fournit en
clair — plus précis que n'importe quelle table qu'on maintiendrait à la main.
"""

from __future__ import annotations

DOMAINES: dict[str, str] = {
    "A": "agriculture pêche espaces naturels espaces verts soins aux animaux",
    "B": "arts artisanat façonnage ouvrages d'art",
    "C": "banque assurance immobilier finance",
    "D": "commerce vente grande distribution",
    "E": "communication média multimédia édition",
    "F": "construction bâtiment travaux publics",
    "G": "hôtellerie restauration tourisme loisirs animation",
    "H": "industrie production maintenance industrielle",
    "I": "installation maintenance",
    "J": "santé médical paramédical",
    "K": "services à la personne services à la collectivité",
    "L": "spectacle culture",
    "M": "support à l'entreprise gestion administration ressources humaines "
         "informatique marketing conseil",
    "N": "transport logistique",
}


def domaine(code_rome: str | None) -> str:
    """Libellé du grand domaine, ou chaîne vide si le code est absent/inconnu."""
    if not code_rome:
        return ""
    return DOMAINES.get(code_rome.strip()[:1].upper(), "")
