"""Génération du dossier de candidature pour une offre."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..config import reglages
from ..db import get_session
from ..documents.cv_render import ModeleIntrouvable
from ..documents.dossier import generer, ouvrir
from ..llm.redaction import etat, redacteur
from ..llm.client import LlmErreur
from ..models import Application, Offer
from ..models.base import maintenant
from ..schemas.document import ResultatDocuments
from ..services.scoring import ProfilVide, profil_courant

log = logging.getLogger("dreamjob.documents")

router = APIRouter(prefix="/api/offres", tags=["documents"])


@router.post("/{offre_id}/documents", response_model=ResultatDocuments)
def generer_documents(
    offre_id: int,
    ouvrir_dossier: bool | None = None,
    session: Session = Depends(get_session),
) -> ResultatDocuments:
    """Écrit CV, lettre et offre archivée dans un dossier daté, en Word et PDF."""
    offre = session.get(Offer, offre_id)
    if offre is None:
        raise HTTPException(404, "Offre introuvable.")

    r = reglages()
    try:
        profil = profil_courant(session)
    except ProfilVide as e:
        raise HTTPException(409, str(e)) from e

    pret, probleme = etat(r)
    if not pret:
        # Sans rédacteur, on livrerait un CV sans lettre : autant le dire avant.
        raise HTTPException(503, probleme)

    ouvrir_apres = r.documents.ouvrir_le_dossier if ouvrir_dossier is None else ouvrir_dossier

    try:
        resultat = generer(
            profil, offre,
            r.chemins.candidatures, r.chemins.cv_modele,
            redacteur=redacteur(r),
            tentatives_lettre=r.llm.tentatives_anti_invention,
            relecture_lettre=r.llm.relecture_lettre,
            reordonner_cv=r.documents.reordonner_cv,
            ouvrir_apres=ouvrir_apres,
        )
    except ModeleIntrouvable as e:
        raise HTTPException(422, str(e)) from e
    except LlmErreur as e:
        raise HTTPException(502, str(e)) from e

    # Le dossier rejoint la candidature si elle existe déjà : l'onglet
    # Candidatures doit pouvoir y renvoyer.
    candidature = session.exec(
        select(Application).where(Application.offer_id == offre_id)
    ).first()
    if candidature is not None:
        candidature.dossier_local = str(resultat.dossier)
        candidature.updated_at = maintenant()
        session.add(candidature)
        session.commit()

    return ResultatDocuments(
        dossier=str(resultat.dossier),
        fichiers=[f.name for f in resultat.fichiers],
        avertissements=resultat.avertissements,
        lettre_essais=resultat.lettre_essais,
        ouvert=ouvrir_apres and "Le dossier n'a pas pu être ouvert automatiquement."
        not in resultat.avertissements,
    )


@router.post("/{offre_id}/documents/ouvrir")
def ouvrir_dossier_existant(offre_id: int, session: Session = Depends(get_session)) -> dict:
    """Rouvre le dossier déjà généré, sans rien régénérer."""
    candidature = session.exec(
        select(Application).where(Application.offer_id == offre_id)
    ).first()
    if candidature is None or not candidature.dossier_local:
        raise HTTPException(404, "Aucun dossier généré pour cette offre.")

    from pathlib import Path

    dossier = Path(candidature.dossier_local)
    if not dossier.exists():
        raise HTTPException(404, f"Le dossier n'existe plus : {dossier}")
    return {"ouvert": ouvrir(dossier), "dossier": str(dossier)}
