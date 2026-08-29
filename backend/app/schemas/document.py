"""Formes exposées par l'API pour la génération de documents."""

from __future__ import annotations

from pydantic import BaseModel


class ResultatDocuments(BaseModel):
    dossier: str
    fichiers: list[str]
    avertissements: list[str]
    lettre_essais: int
    ouvert: bool
