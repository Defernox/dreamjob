"""Endpoints de service : état de l'installation, vocabulaires, réglages.

Le front s'en sert pour construire ses filtres et afficher les avertissements
(clé LLM absente, LibreOffice introuvable, modèle de CV manquant).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter

from ..config import RACINE, recharger, reglages
from ..models import CONTRATS, PAYS_FILTRES, STATUTS

router = APIRouter(prefix="/api", tags=["meta"])

# Emplacements habituels de LibreOffice sous Windows, puis PATH (macOS/Linux).
_CHEMINS_SOFFICE = [
    Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
    Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
]


def chemin_soffice() -> str | None:
    for c in _CHEMINS_SOFFICE:
        if c.exists():
            return str(c)
    trouve = shutil.which("soffice") or shutil.which("libreoffice")
    return trouve


@router.get("/sante")
def sante() -> dict:
    r = reglages()
    soffice = chemin_soffice()
    return {
        "ok": True,
        "racine": str(RACINE),
        "base_donnees": str(r.chemins.db),
        "base_existe": r.chemins.db.exists(),
        "llm": {
            "disponible": r.llm_disponible,
            "modele_extraction": r.llm.modele_extraction,
            "modele_redaction": r.llm.modele_redaction,
            "message": None if r.llm_disponible
            else "Aucune ANTHROPIC_API_KEY dans .env : mode dégradé "
                 "(scoring lexical, ni import de CV ni lettre de motivation).",
        },
        "pdf": {
            "disponible": soffice is not None,
            "chemin": soffice,
            "message": None if soffice
            else "LibreOffice introuvable : les documents seront générés en Word uniquement.",
        },
        "modele_cv": {
            "chemin": str(r.chemins.cv_modele),
            "present": r.chemins.cv_modele.exists(),
        },
        "dossier_candidatures": str(r.chemins.candidatures),
        "sources": [
            {"cle": k, "libelle": s.libelle or k, "actif": s.actif, "remarque": s.remarque}
            for k, s in r.sources.items()
        ],
    }


@router.get("/reglages")
def lire_reglages() -> dict:
    r = reglages()
    return {
        "scoring": {
            "version": r.scoring.version,
            "poids": r.scoring.poids.model_dump(),
            "poids_normalises": r.scoring.poids.normalises(),
            "seuils": r.scoring.seuils.model_dump(),
        },
        "vocabulaires": {
            "contrats": CONTRATS,
            "statuts": STATUTS,
            "pays": PAYS_FILTRES,
        },
        "recherche": r.recherche.model_dump(),
    }


@router.post("/reglages/recharger")
def recharger_reglages() -> dict:
    """Relit config.yaml à chaud (utile après avoir modifié les poids)."""
    r = recharger()
    return {"ok": True, "version_scoring": r.scoring.version, "poids": r.scoring.poids.model_dump()}
