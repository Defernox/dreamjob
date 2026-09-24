"""Une candidature : le suivi, et le justificatif France Travail."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from .base import maintenant
from .enums import StatutCandidature


class Application(SQLModel, table=True):
    __tablename__ = "application"
    __table_args__ = (
        # Unique PAR utilisateur : cliquer deux fois sur « Postuler » ne crée
        # pas deux lignes, mais deux amis peuvent postuler à la même annonce.
        Index("ix_application_utilisateur_offre", "utilisateur_id", "offer_id", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    utilisateur_id: int | None = Field(default=None, foreign_key="utilisateur.id", index=True)
    offer_id: int = Field(foreign_key="offer.id", index=True)

    date_candidature: datetime = Field(default_factory=maintenant)
    statut: str = Field(default=StatutCandidature.ENVOYEE.value, index=True)
    deadline: date | None = None
    notes: str = ""
    contact: str = ""
    dossier_local: str = ""      # dossier CV + lettre généré

    created_at: datetime = Field(default_factory=maintenant)
    updated_at: datetime = Field(default_factory=maintenant)
