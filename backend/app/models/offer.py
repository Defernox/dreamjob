"""Une offre d'emploi récupérée chez une source."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from .base import colonne_json, maintenant


class Offer(SQLModel, table=True):
    __tablename__ = "offer"
    __table_args__ = (
        # Deux filets de déduplication, pour deux problèmes différents :
        #  - (source, source_id) : relancer le même scan ne recrée rien
        UniqueConstraint("source", "source_id", name="uq_offer_source"),
        #  - hash : la même annonce republiée sur un autre site est reconnue
        Index("ix_offer_hash", "hash", unique=True),
        Index("ix_offer_date_publication", "date_publication"),
    )

    id: int | None = Field(default=None, primary_key=True)

    # --- Provenance ---
    source: str = Field(index=True)              # cle du connecteur : "france_travail"
    source_id: str                               # identifiant chez la source
    url: str = ""

    # --- Contenu ---
    titre: str = ""
    entreprise: str = ""
    lieu: str = ""
    pays: str = Field(default="", index=True)
    type_contrat: str = Field(default="", index=True)
    date_publication: datetime | None = None
    date_recuperation: datetime = Field(default_factory=maintenant)
    description_brute: str = ""

    hash: str = ""

    # Le score et « déjà vue » dépendent de l'utilisateur : ils vivent dans
    # `ScoreOffre`. Ici ne reste que ce qui ne dépend que de l'annonce.

    # --- Signaux de l'offre (langue, vocabulaire, secteur), en pur code ---
    # {"version": 3, "langue": "fr", "vocabulaire": [...], ...}
    extraction: dict = Field(default_factory=dict, sa_column=colonne_json())
    extraction_modele: str = ""
    extraction_at: datetime | None = None

    # Charge utile d'origine, archivee telle quelle (l'annonce peut disparaitre)
    raw: dict = Field(default_factory=dict, sa_column=colonne_json())

    # Dernière fois qu'un scan a revu cette annonce chez sa source. Une offre
    # retirée du site cesse d'être revue : c'est ce qui permet de repérer celles
    # auxquelles il ne sert plus à rien de postuler.
    derniere_vue_le: datetime = Field(default_factory=maintenant, index=True)
