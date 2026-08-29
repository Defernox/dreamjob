"""Formes exposées par l'API pour les candidatures."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, field_validator

from ..models.enums import STATUTS


class CandidatureCreation(BaseModel):
    offer_id: int
    statut: str | None = None       # défaut : « Envoyée »
    notes: str = ""
    contact: str = ""
    deadline: date | None = None

    @field_validator("statut")
    @classmethod
    def _statut_connu(cls, valeur: str | None) -> str | None:
        if valeur is not None and valeur not in STATUTS:
            raise ValueError(f"Statut inconnu. Valeurs acceptées : {', '.join(STATUTS)}")
        return valeur


class CandidatureMaj(BaseModel):
    statut: str | None = None
    notes: str | None = None
    contact: str | None = None
    deadline: date | None = None
    dossier_local: str | None = None

    @field_validator("statut")
    @classmethod
    def _statut_connu(cls, valeur: str | None) -> str | None:
        if valeur is not None and valeur not in STATUTS:
            raise ValueError(f"Statut inconnu. Valeurs acceptées : {', '.join(STATUTS)}")
        return valeur


class CandidatureLecture(BaseModel):
    id: int
    offer_id: int
    date_candidature: datetime
    statut: str
    deadline: date | None
    notes: str
    contact: str
    dossier_local: str
    updated_at: datetime

    # Repris de l'offre : le tableau de suivi doit se lire sans jointure côté client.
    titre: str = ""
    entreprise: str = ""
    pays: str = ""
    score: float | None = None
    url: str = ""
