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

# Ordre d'affichage des pays dans les filtres (écran Offres)
PAYS_FILTRES = [
    "Belgique", "Canada", "France", "Luxembourg", "Maroc",
    "Royaume-Uni", "Sénégal", "Suisse", "Tunisie", "États-Unis",
]
