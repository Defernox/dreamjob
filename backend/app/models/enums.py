"""Vocabulaires métier.

Ces valeurs sont stockées en base sous forme de texte simple (pas de type ENUM
SQL) : ajouter un type de contrat ne demandera donc aucune migration. La
validation se fait à l'entrée, dans la couche API.
"""

from __future__ import annotations

from enum import Enum


class TypeContrat(str, Enum):
    CDI = "CDI"
    CDD = "CDD"
    VIE = "V.I.E"
    STAGE = "Stage"
    ALTERNANCE = "Alternance"
    INTERIM = "Intérim"
    FREELANCE = "Freelance"
    AUTRE = "Autre"


class StatutCandidature(str, Enum):
    A_POSTULER = "À postuler"
    ENVOYEE = "Envoyée"
    RELANCEE = "Relancée"
    ENTRETIEN = "Entretien"
    REFUS = "Refus"
    ACCEPTEE = "Acceptée"


class StatutScan(str, Enum):
    EN_COURS = "en cours"
    TERMINE = "terminé"
    PARTIEL = "partiel"      # au moins un connecteur en erreur
    ECHEC = "échec"          # aucun connecteur n'a abouti


class TypeCacheLlm(str, Enum):
    EXTRACTION = "extraction"      # compétences / secteur / langue d'une offre
    LETTRE = "lettre"              # lettre de motivation
    IMPORT_CV = "import_cv"        # structuration d'un CV en profil


CONTRATS = [c.value for c in TypeContrat]
STATUTS = [s.value for s in StatutCandidature]

# Pays proposés dans les filtres et dans les préférences du profil.
# Regroupés par zone : quarante chips à plat seraient illisibles.
# Le choix penche vers les places financières et les pays francophones —
# c'est ce que vise ce profil, pas une liste exhaustive de l'ONU.
PAYS_PAR_ZONE: dict[str, list[str]] = {
    "Europe": [
        "Allemagne", "Autriche", "Belgique", "Chypre", "Danemark", "Espagne",
        "France", "Irlande", "Italie", "Liechtenstein", "Luxembourg", "Malte",
        "Monaco", "Norvège", "Pays-Bas", "Pologne", "Portugal", "Royaume-Uni",
        "Suède", "Suisse", "Tchéquie",
    ],
    "Amérique": ["Brésil", "Canada", "États-Unis", "Mexique"],
    "Asie-Pacifique": [
        "Australie", "Chine", "Hong Kong", "Inde", "Japon",
        "Nouvelle-Zélande", "Singapour",
    ],
    "Afrique et Moyen-Orient": [
        "Afrique du Sud", "Algérie", "Côte d'Ivoire", "Émirats arabes unis",
        "Israël", "Île Maurice", "Maroc", "Qatar", "Sénégal", "Tunisie",
    ],
}

# Liste à plat, pour les filtres de l'écran Offres et la validation.
PAYS_FILTRES = [pays for zone in PAYS_PAR_ZONE.values() for pays in zone]
