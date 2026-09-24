"""Une recherche enregistrée.

Un profil ne se résume pas à un jeu de mots-clés : on cherche « analyste
risques », « middle office » et « V.I.E finance » en même temps, parfois sur des
pays différents. Une seule requête dans `config.yaml` obligeait à choisir.

Chaque recherche active est jouée à chaque scan, et leurs résultats sont
dédupliqués ensemble — une offre trouvée par deux recherches n'est stockée
qu'une fois.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from .base import colonne_json, maintenant


class Recherche(SQLModel, table=True):
    __tablename__ = "recherche"
    __table_args__ = (
        # Un nom unique PAR utilisateur : deux amis peuvent chacun avoir leur
        # « CDI Paris ».
        Index("ix_recherche_utilisateur_nom", "utilisateur_id", "nom", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    utilisateur_id: int | None = Field(default=None, foreign_key="utilisateur.id", index=True)
    nom: str = Field(index=True)

    mots_cles: list = Field(default_factory=list, sa_column=colonne_json())
    # Vides = on reprend les préférences du profil. Renseignés, ils les
    # remplacent : « V.I.E finance » n'a pas les mêmes pays que « CDI Paris ».
    pays: list = Field(default_factory=list, sa_column=colonne_json())
    contrats: list = Field(default_factory=list, sa_column=colonne_json())

    departement: str = ""
    publiee_depuis_jours: int | None = None
    max_offres: int = 150

    active: bool = Field(default=True, index=True)
    ordre: int = 0

    created_at: datetime = Field(default_factory=maintenant)
    updated_at: datetime = Field(default_factory=maintenant)
