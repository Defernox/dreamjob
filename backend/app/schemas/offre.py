"""Formes exposées par l'API pour les offres."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OffreResume(BaseModel):
    """Ce qu'une carte de la grille a besoin d'afficher — pas la description."""

    id: int
    source: str
    url: str
    titre: str
    entreprise: str
    lieu: str
    pays: str
    type_contrat: str
    date_publication: datetime | None
    date_recuperation: datetime
    score: float | None
    score_explication: str
    vue: bool
    a_candidature: bool = False


class OffreDetail(OffreResume):
    description_brute: str
    score_detail: dict
    scored_at: datetime | None
    poids_version: int | None


class Compteurs(BaseModel):
    """Compteurs des chips. Chaque facette est comptée en ignorant SON propre
    filtre : sinon un filtre actif afficherait 0 partout ailleurs."""

    contrat: dict[str, int]
    source: dict[str, int]
    pays: dict[str, int]


class PageOffres(BaseModel):
    total: int
    offres: list[OffreResume]
    compteurs: Compteurs


class Statistiques(BaseModel):
    total: int
    aujourd_hui: int
    vie: int
    # Arrivées à la dernière recherche et pas encore ouvertes : c'est le badge.
    nouvelles: int
    # Toutes celles jamais ouvertes, tous scans confondus.
    jamais_vues: int
    non_scorees: int
    dernier_scan: datetime | None


class ResultatScoring(BaseModel):
    scorees: int
    total: int
    version_poids: int
    appels_llm: int
