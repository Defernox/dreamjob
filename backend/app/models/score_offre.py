"""Ce qu'une offre est pour UN utilisateur : sa note, et s'il l'a ouverte.

Les offres sont communes — une annonce trouvée pour deux personnes n'est
stockée qu'une fois. Mais le score dépend du profil, et « déjà vue » de celui
qui regarde : ni l'un ni l'autre ne peut vivre sur l'offre.

**Une ligne ici, c'est aussi l'appartenance au fil de l'utilisateur.** Une offre
n'apparaît chez quelqu'un que si l'une de SES recherches l'a ramenée : l'ami qui
cherche en marketing n'a pas à parcourir deux mille offres de finance, et une
source réservée au propriétaire ne fuit pas chez les autres.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from .base import colonne_json, maintenant


class ScoreOffre(SQLModel, table=True):
    __tablename__ = "score_offre"
    __table_args__ = (
        Index("ix_score_offre_utilisateur_score", "utilisateur_id", "score"),
        Index("ix_score_offre_utilisateur_vue", "utilisateur_id", "vue"),
    )

    utilisateur_id: int = Field(foreign_key="utilisateur.id", primary_key=True)
    offer_id: int = Field(foreign_key="offer.id", primary_key=True, index=True)

    score: float | None = None
    # {"competences": 82.0, "secteur": 60.0, "pays": 100.0, ...}
    score_detail: dict = Field(default_factory=dict, sa_column=colonne_json())
    score_explication: str = ""
    scored_at: datetime | None = None
    poids_version: int | None = None             # version des poids ayant produit ce score
    # Version des signaux de l'offre ayant produit ce score. Les signaux vivent
    # sur l'offre et sont recalculés par le premier qui la rescore : sans ce
    # compteur, les autres garderaient une note tirée de signaux périmés.
    version_signaux: int | None = None

    vue: bool = False
    # Entrée dans le fil de CET utilisateur — pas la date de l'offre. Une offre
    # déjà en base, ramenée pour la première fois par la recherche d'un ami, est
    # une nouveauté pour lui.
    ajoutee_le: datetime = Field(default_factory=maintenant, index=True)
    # Quand une alerte l'a signalée — la veille ou le résumé du matin. Une offre
    # n'est jamais signalée deux fois, et c'est ce qui compte les alertes du jour.
    alertee_le: datetime | None = None


class DepenseLlm(SQLModel, table=True):
    """Ce qu'a coûté un dossier, et à qui : c'est ce qui borne le budget d'un ami."""

    __tablename__ = "depense_llm"

    id: int | None = Field(default=None, primary_key=True)
    utilisateur_id: int = Field(foreign_key="utilisateur.id", index=True)
    offer_id: int | None = Field(default=None, foreign_key="offer.id")
    le: datetime = Field(default_factory=maintenant, index=True)
    cout_usd: float = 0.0
