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
from .utilisateur import SessionUtilisateur, Utilisateur

__all__ = [
    "Application", "LlmCache", "Offer", "Profile", "Recherche", "ScanRun",
    "SessionUtilisateur", "Utilisateur",
    "TypeContrat", "StatutCandidature", "StatutScan", "TypeCacheLlm",
    "CONTRATS", "STATUTS", "PAYS_FILTRES",
]
