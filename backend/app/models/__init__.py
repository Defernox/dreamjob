"""Toutes les tables. Importer ce module suffit à peupler SQLModel.metadata."""

from .application import Application
from .enums import (
    CONTRATS,
    PAYS_FILTRES,
    STATUTS,
    StatutCandidature,
    StatutScan,
    TypeCacheLlm,
    TypeContrat,
)
from .llm_cache import LlmCache
from .offer import Offer
from .profile import Profile
from .recherche import Recherche
from .scan_run import ScanRun
from .score_offre import DepenseLlm, ScoreOffre
from .utilisateur import EMAIL_LOCAL, SessionUtilisateur, Utilisateur

__all__ = [
    "Application", "DepenseLlm", "LlmCache", "Offer", "Profile", "Recherche", "ScanRun",
    "ScoreOffre", "SessionUtilisateur", "Utilisateur", "EMAIL_LOCAL",
    "TypeContrat", "StatutCandidature", "StatutScan", "TypeCacheLlm",
    "CONTRATS", "STATUTS", "PAYS_FILTRES",
]
