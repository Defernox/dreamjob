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
        Index("ix_offer_score", "score"),
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

    # --- Scoring ---
    score: float | None = None
    # {"competences": 82.0, "secteur": 60.0, "pays": 100.0, "langue": 100.0, "contrat": 100.0}
    score_detail: dict = Field(default_factory=dict, sa_column=colonne_json())
    score_explication: str = ""
    scored_at: datetime | None = None
    poids_version: int | None = None             # version des poids ayant produit ce score

    # --- Extraction LLM, mise en cache : jamais rejouee pour un meme hash ---
    # {"competences": [...], "secteur": "...", "langue": "fr", "contrat_detecte": "CDI"}
    extraction: dict = Field(default_factory=dict, sa_column=colonne_json())
    extraction_modele: str = ""
    extraction_at: datetime | None = None

    # Charge utile d'origine, archivee telle quelle (l'annonce peut disparaitre)
    raw: dict = Field(default_factory=dict, sa_column=colonne_json())

    # Badge « X nouvelles offres »
    vue: bool = Field(default=False, index=True)
