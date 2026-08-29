"""Helpers communs aux tables."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Column


def maintenant() -> datetime:
    """Horodatage UTC *naïf*.

    SQLite ne conserve pas le fuseau : on stocke donc systématiquement de l'UTC
    sans tzinfo, et l'API renvoie des ISO suffixés « Z ». Aucune date locale
    n'entre en base.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def colonne_json(nullable: bool = False) -> Column:
    return Column(JSON, nullable=nullable)
