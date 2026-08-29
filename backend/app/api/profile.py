"""Le profil : lecture, édition, import depuis un CV."""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select

from ..config import reglages
from ..db import get_session
from ..importers.cv_import import (
    EXTENSIONS,
    CvIllisible,
    FormatNonSupporte,
    importer_cv,
)
from ..llm.client import LlmErreur, LlmIndisponible
from ..models import Profile
from ..models.base import maintenant
from ..schemas.profile import ProfilLecture, ProfilMaj, ResultatImport

log = logging.getLogger("dreamjob.profil")

router = APIRouter(prefix="/api/profil", tags=["profil"])

TAILLE_MAX = 10 * 1024 * 1024  # 10 Mo : très au-delà d'un CV normal


def profil_courant(session: Session) -> Profile:
    """Le profil unique. Créé vide au premier appel plutôt que renvoyer 404."""
    profil = session.exec(select(Profile).order_by(Profile.id)).first()
    if profil is None:
        profil = Profile()
        session.add(profil)
        session.commit()
        session.refresh(profil)
    return profil


def _en_lecture(profil: Profile) -> ProfilLecture:
    return ProfilLecture.model_validate(profil.model_dump())


def _nom_sur(nom: str) -> str:
    """Neutralise un nom de fichier venant de l'extérieur avant de l'écrire."""
    base = Path(nom).name
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "cv"
    return base[:120]


@router.get("", response_model=ProfilLecture)
def lire(session: Session = Depends(get_session)) -> ProfilLecture:
    return _en_lecture(profil_courant(session))


@router.put("", response_model=ProfilLecture)
def enregistrer(maj: ProfilMaj, session: Session = Depends(get_session)) -> ProfilLecture:
    profil = profil_courant(session)
    for champ, valeur in maj.model_dump(mode="json").items():
        setattr(profil, champ, valeur)
    profil.updated_at = maintenant()
    session.add(profil)
    session.commit()
    session.refresh(profil)
    return _en_lecture(profil)


@router.post("/importer", response_model=ResultatImport)
async def importer(
    fichier: UploadFile = File(...),
    forcer: bool = False,
    session: Session = Depends(get_session),
) -> ResultatImport:
    """Lit un CV .docx/.pdf et en déduit le profil.

    Les préférences (pays et contrats acceptés) ne figurent pas dans un CV :
    elles sont conservées telles quelles, jamais devinées.
    """
    suffixe = Path(fichier.filename or "").suffix.lower()
    if suffixe not in EXTENSIONS:
        raise HTTPException(400, f"Formats acceptés : {', '.join(sorted(EXTENSIONS))}")

    contenu = await fichier.read()
    if len(contenu) > TAILLE_MAX:
        raise HTTPException(413, "Fichier trop volumineux (10 Mo maximum).")

    dossier = reglages().chemins.dossier_cache / "cv"
    dossier.mkdir(parents=True, exist_ok=True)
    destination = dossier / _nom_sur(fichier.filename or f"cv{suffixe}")
    destination.write_bytes(contenu)

    try:
        structure, depuis_cache, modele, caracteres = importer_cv(
            destination, session, forcer=forcer
        )
    except FormatNonSupporte as e:
        raise HTTPException(400, str(e)) from e
    except CvIllisible as e:
        raise HTTPException(422, str(e)) from e
    except LlmIndisponible as e:
        raise HTTPException(503, str(e)) from e
    except LlmErreur as e:
        raise HTTPException(502, str(e)) from e

    profil = profil_courant(session)
    for champ, valeur in structure.model_dump(mode="json").items():
        setattr(profil, champ, valeur)
    profil.cv_source_path = str(destination)
    profil.cv_importe_le = maintenant()
    profil.updated_at = maintenant()
    session.add(profil)
    session.commit()
    session.refresh(profil)

    avertissements = []
    if not profil.pays_acceptes:
        avertissements.append(
            "Renseignez les pays acceptés : sans eux, le critère « pays » du score reste à zéro."
        )
    if not profil.contrats_acceptes:
        avertissements.append(
            "Renseignez les types de contrat acceptés, du plus souhaité au moins souhaité."
        )
    if not profil.skills:
        avertissements.append("Aucune compétence détectée — vérifiez le fichier importé.")

    return ResultatImport(
        profil=_en_lecture(profil),
        depuis_cache=depuis_cache,
        modele=modele,
        fichier=destination.name,
        caracteres_lus=caracteres,
        avertissements=avertissements,
    )
