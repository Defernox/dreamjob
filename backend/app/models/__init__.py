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
from .scan_run import ScanRun

__all__ = [
    "Application", "LlmCache", "Offer", "Profile", "ScanRun",
    "TypeContrat", "StatutCandidature", "StatutScan", "TypeCacheLlm",
    "CONTRATS", "STATUTS", "PAYS_FILTRES",
]
