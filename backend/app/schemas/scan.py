"""Formes exposées par l'API pour les scans."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RequeteScan(BaseModel):
    """Surcharge facultative de la recherche par défaut de config.yaml."""

    mots_cles: list[str] | None = None
    pays: list[str] | None = None
    contrats: list[str] | None = None
    departement: str | None = None
    publiee_depuis_jours: int | None = None
    max_offres: int | None = Field(default=None, ge=1, le=3000)
    sources: list[str] | None = None


class ErreurSource(BaseModel):
    source: str
    type: str          # non_configure | panne | inattendu
    erreur: str


class ScanLecture(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    statut: str
    declenche_par: str
    sources: list[str]
    requete: dict
    nb_recuperees: int
    nb_nouvelles: int
    nb_doublons: int
    nb_rejetees: int
    nb_appels_llm: int
    erreurs: list[ErreurSource]
