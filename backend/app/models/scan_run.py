"""Trace d'un scan : ce qui a été interrogé, ramené, et ce qui a cassé."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from .base import colonne_json, maintenant
from .enums import StatutScan


class ScanRun(SQLModel, table=True):
    __tablename__ = "scan_run"

    id: int | None = Field(default=None, primary_key=True)

    started_at: datetime = Field(default_factory=maintenant, index=True)
    finished_at: datetime | None = None

    sources: list = Field(default_factory=list, sa_column=colonne_json())
    requete: dict = Field(default_factory=dict, sa_column=colonne_json())

    nb_recuperees: int = 0     # offres remontées par les sources
    nb_nouvelles: int = 0      # réellement insérées
    nb_doublons: int = 0       # écartées par (source, source_id) ou par hash
    nb_rejetees: int = 0       # écartées par les filtres (pays, contrat…)
    nb_appels_llm: int = 0     # doit rester à 0 sur un second scan identique

    # [{"source": "adzuna", "erreur": "401 Unauthorized"}]
    # Un connecteur en panne n'interrompt jamais les autres.
    erreurs: list = Field(default_factory=list, sa_column=colonne_json())
    statut: str = Field(default=StatutScan.EN_COURS.value)

    declenche_par: str = "manuel"    # "manuel" | "planifie"
