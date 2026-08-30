"""Formes exposées par l'API pour la génération de documents."""

from __future__ import annotations

from pydantic import BaseModel


class ResultatDocuments(BaseModel):
    dossier: str
    fichiers: list[str]
    avertissements: list[str]
    lettre_essais: int
    ouvert: bool
    # Ce que l'offre réclame et que le profil ne couvre pas. Ne juge pas
    # l'offre : dit ce qui manque au candidat pour cette famille de postes.
    mots_cles_non_couverts: list[str] = []
