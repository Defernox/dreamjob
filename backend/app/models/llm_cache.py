"""Cache des appels LLM.

C'est la pièce qui garantit qu'un second scan ne rappelle jamais le modèle :
la clé dérive du hash de l'offre, du type d'appel et du modèle utilisé.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlmodel import Field, SQLModel

from .base import colonne_json, maintenant


class LlmCache(SQLModel, table=True):
    __tablename__ = "llm_cache"

    cle: str = Field(primary_key=True)
    type: str = Field(index=True)           # cf. TypeCacheLlm
    hash_source: str = Field(index=True)    # hash de l'offre (ou du CV)
    modele: str = ""
    payload: dict = Field(default_factory=dict, sa_column=colonne_json())
    created_at: datetime = Field(default_factory=maintenant)

    @staticmethod
    def construire_cle(type_: str, hash_source: str, modele: str, variante: str = "") -> str:
        brut = f"{type_}|{hash_source}|{modele}|{variante}"
        return hashlib.sha256(brut.encode("utf-8")).hexdigest()
