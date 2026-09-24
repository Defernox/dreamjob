"""Comptes et sessions — l'application hébergée n'est ouverte qu'à qui se connecte.

En local, rien de tout cela ne sert : l'API n'écoute que sur 127.0.0.1. Sur un
serveur, le profil contient un téléphone, un e-mail et un parcours complet ; il
ne doit s'afficher qu'à son propriétaire, même derrière un réseau privé.

Chaque compte a ses propres données : profil, recherches, scores, candidatures,
documents. Seules les offres sont communes — une annonce trouvée pour deux
personnes n'est stockée qu'une fois, mais chacun ne voit que celles que SES
recherches ont ramenées (`ScoreOffre`).

**Le propriétaire** est le compte qui a installé l'application. Il reprend les
données d'avant les comptes, et lui seul reçoit les sources dont l'usage est
personnel (DogFinance). En local, sans connexion, c'est lui qu'on sert.
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
    proprietaire: bool = False
    # Dollars d'API par mois civil, pour la génération des dossiers. None =
    # sans limite (le propriétaire, qui paie la clé). Un ami reçoit le budget
    # par défaut de config.yaml, modifiable par `python -m app.compte budget`.
    budget_mensuel_usd: float | None = None


# Adresse du compte créé d'office quand aucun n'existe : il porte les données
# d'une installation locale, qui n'a jamais eu besoin de se connecter. Son mot
# de passe vide ne vérifie jamais — on ne peut pas s'y connecter tant que
# `python -m app.compte creer` ne l'a pas repris.
EMAIL_LOCAL = "local"


class SessionUtilisateur(SQLModel, table=True):
    """Une connexion ouverte. On stocke l'EMPREINTE du jeton, jamais le jeton :
    une copie de la base ne suffit pas à se faire passer pour quelqu'un."""

    empreinte: str = Field(primary_key=True)
    utilisateur_id: int = Field(foreign_key="utilisateur.id", index=True)
    cree_le: datetime = Field(default_factory=maintenant)
    expire_le: datetime
