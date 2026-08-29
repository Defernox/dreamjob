"""Formes exposées par l'API pour les recherches enregistrées."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from ..models.enums import CONTRATS, PAYS_FILTRES


class RechercheEcriture(BaseModel):
    nom: str = Field(min_length=1, max_length=60)
    mots_cles: list[str] = Field(default_factory=list)
    # Vides = les préférences du profil s'appliquent.
    pays: list[str] = Field(default_factory=list)
    contrats: list[str] = Field(default_factory=list)
    departement: str = ""
    publiee_depuis_jours: int | None = Field(default=None, ge=1, le=365)
    max_offres: int = Field(default=150, ge=1, le=3000)
    active: bool = True
    ordre: int = 0

    @field_validator("contrats")
    @classmethod
    def _contrats_connus(cls, valeurs: list[str]) -> list[str]:
        inconnus = [v for v in valeurs if v not in CONTRATS]
        if inconnus:
            raise ValueError(f"Contrat inconnu : {', '.join(inconnus)}")
        return valeurs

    @field_validator("pays")
    @classmethod
    def _pays_connus(cls, valeurs: list[str]) -> list[str]:
        inconnus = [v for v in valeurs if v not in PAYS_FILTRES]
        if inconnus:
            raise ValueError(f"Pays inconnu : {', '.join(inconnus)}")
        return valeurs

    @field_validator("nom")
    @classmethod
    def _nom_lisible(cls, valeur: str) -> str:
        nettoye = valeur.strip()
        if not nettoye:
            raise ValueError("Le nom ne peut pas être vide.")
        return nettoye


class RechercheMaj(RechercheEcriture):
    nom: str | None = Field(default=None, min_length=1, max_length=60)


class RechercheLecture(RechercheEcriture):
    id: int
    updated_at: datetime
