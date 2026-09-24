"""Comptes et sessions — l'application hébergée n'est ouverte qu'à qui se connecte.

En local, rien de tout cela ne sert : l'API n'écoute que sur 127.0.0.1. Sur un
serveur, le profil contient un téléphone, un e-mail et un parcours complet ; il
ne doit s'afficher qu'à son propriétaire, même derrière un réseau privé.

Les comptes précèdent le multi-utilisateur : les données restent communes pour
l'instant, mais ouvrir l'application à un ami deviendra une extension de ce
modèle, pas une réécriture.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from .base import maintenant


class Utilisateur(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    # scrypt, sel aléatoire, au format « scrypt$n$r$p$sel$empreinte ». Le mot de
    # passe lui-même n'est jamais stocké, ni journalisé.
    mot_de_passe: str
    cree_le: datetime = Field(default_factory=maintenant)
    derniere_connexion: datetime | None = None


class SessionUtilisateur(SQLModel, table=True):
    """Une connexion ouverte. On stocke l'EMPREINTE du jeton, jamais le jeton :
    une copie de la base ne suffit pas à se faire passer pour quelqu'un."""

    empreinte: str = Field(primary_key=True)
    utilisateur_id: int = Field(foreign_key="utilisateur.id", index=True)
    cree_le: datetime = Field(default_factory=maintenant)
    expire_le: datetime
