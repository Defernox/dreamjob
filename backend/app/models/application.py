"""Une candidature : le suivi, et le justificatif France Travail."""

from __future__ import annotations

from datetime import date, datetime

from sqlmodel import Field, SQLModel

from .base import maintenant
from .enums import StatutCandidature


class Application(SQLModel, table=True):
    __tablename__ = "application"

    id: int | None = Field(default=None, primary_key=True)
    # unique : cliquer deux fois sur « Postuler » ne crée pas deux lignes.
    offer_id: int = Field(foreign_key="offer.id", unique=True, index=True)

    date_candidature: datetime = Field(default_factory=maintenant)
    statut: str = Field(default=StatutCandidature.ENVOYEE.value, index=True)
    deadline: date | None = None
    notes: str = ""
    contact: str = ""
    dossier_local: str = ""      # dossier CV + lettre généré

    created_at: datetime = Field(default_factory=maintenant)
    updated_at: datetime = Field(default_factory=maintenant)
