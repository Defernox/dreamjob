"""Sauvegarde de la base au démarrage.

Tout le travail de l'utilisateur — profil, offres, candidatures, dossiers
générés — vit dans un seul fichier SQLite. Une copie datée à chaque ouverture
coûte quelques millisecondes et évite de tout reperdre.

La copie passe par l'API `backup` de SQLite, jamais par un `copy` de fichier :
en mode WAL, les écritures récentes vivent dans un journal annexe, et copier le
seul `.db` produirait une sauvegarde amputée.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date
from pathlib import Path

log = logging.getLogger("dreamjob.sauvegarde")

MOTIF = "dreamjob-{jour}.db"


def sauvegarder(base: Path, dossier: Path, a_conserver: int = 7) -> Path | None:
    """Copie la base du jour et retire les sauvegardes trop anciennes.

    Renvoie le chemin de la copie, ou None s'il n'y avait rien à sauvegarder.
    Une sauvegarde qui échoue ne doit jamais empêcher l'application de démarrer.
    """
    if not base.exists():
        return None

    dossier.mkdir(parents=True, exist_ok=True)
    destination = dossier / MOTIF.format(jour=date.today().isoformat())

    try:
        source = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
        try:
            copie = sqlite3.connect(destination)
            try:
                source.backup(copie)
            finally:
                copie.close()
        finally:
            source.close()
    except sqlite3.Error as e:
        log.warning("Sauvegarde impossible : %s", e)
        return None

    _faire_le_menage(dossier, a_conserver)
    log.info("Base sauvegardée : %s", destination.name)
    return destination


def _faire_le_menage(dossier: Path, a_conserver: int) -> None:
    """Ne garde que les N sauvegardes les plus récentes."""
    copies = sorted(dossier.glob("dreamjob-*.db"), reverse=True)
    for vieille in copies[max(a_conserver, 1):]:
        try:
            vieille.unlink()
        except OSError as e:  # noqa: PERF203
            log.warning("Suppression de %s impossible : %s", vieille.name, e)
