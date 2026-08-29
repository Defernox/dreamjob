"""Conversion Word → PDF via LibreOffice en ligne de commande.

Sans LibreOffice, l'application ne s'arrête pas : elle livre le Word seul et le
signale. Même principe que le mode dégradé sans clé LLM.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("dreamjob.pdf")

DELAI_MAX = 120  # secondes : le premier lancement de LibreOffice est lent

EMPLACEMENTS = [
    Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
    Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
]


class LibreOfficeIntrouvable(RuntimeError):
    pass


class ConversionEchouee(RuntimeError):
    pass


def chemin_soffice() -> str | None:
    for emplacement in EMPLACEMENTS:
        if emplacement.exists():
            return str(emplacement)
    return shutil.which("soffice") or shutil.which("libreoffice")


def disponible() -> bool:
    return chemin_soffice() is not None


def convertir(source: Path, dossier_sortie: Path | None = None) -> Path:
    """Convertit `source` en PDF dans le même dossier. Renvoie le chemin du PDF."""
    soffice = chemin_soffice()
    if soffice is None:
        raise LibreOfficeIntrouvable(
            "LibreOffice est introuvable : les documents sont générés en Word uniquement. "
            "Installez-le avec : winget install TheDocumentFoundation.LibreOffice"
        )
    if not source.exists():
        raise FileNotFoundError(f"Fichier à convertir introuvable : {source}")

    sortie = dossier_sortie or source.parent
    sortie.mkdir(parents=True, exist_ok=True)

    try:
        resultat = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(sortie), str(source)],
            capture_output=True, text=True, timeout=DELAI_MAX,
        )
    except subprocess.TimeoutExpired as e:
        raise ConversionEchouee(
            f"LibreOffice n'a pas répondu en {DELAI_MAX} s. Fermez-le s'il est déjà ouvert."
        ) from e

    pdf = sortie / f"{source.stem}.pdf"
    if not pdf.exists():
        raise ConversionEchouee(
            f"La conversion PDF a échoué : {(resultat.stderr or resultat.stdout).strip()[:300]}"
        )
    log.info("PDF généré : %s", pdf)
    return pdf
