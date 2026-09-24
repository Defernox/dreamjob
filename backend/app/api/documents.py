"""Génération du dossier de candidature pour une offre."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..config import reglages
from ..db import get_session
from ..documents.cv_render import ModeleIntrouvable
from ..documents.dossier import generer, ouvrir
from ..llm.redaction import cibleur, etat, redacteur
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
    # Sur un serveur, il n'y a pas d'explorateur de fichiers à ouvrir : les
    # documents se téléchargent depuis l'interface.
    ouvrir_apres = ouvrir_apres and not r.serveur

    try:
        resultat = generer(
            profil, offre,
            r.chemins.candidatures, r.chemins.cv_modele,
            redacteur=redacteur(r),
            tentatives_lettre=r.llm.tentatives_anti_invention,
            relecture_lettre=r.llm.relecture_lettre,
            reordonner_cv=r.documents.reordonner_cv,
            ouvrir_apres=ouvrir_apres,
            cibleur=cibleur(r),
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
        mots_cles_non_couverts=resultat.mots_cles_non_couverts,
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


# --- Téléchargement ---------------------------------------------------------
# Sur un serveur, les documents ne s'ouvrent pas dans un explorateur : ils se
# téléchargent. En local aussi, d'ailleurs — c'est plus rapide que de chercher
# le dossier.

TELECHARGEABLES = {".pdf": "application/pdf",
                   ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def _dossier_de(offre: Offer, session: Session) -> Path | None:
    """Le dernier dossier généré pour cette offre.

    La candidature le retient quand elle existe. Sinon — juste après une
    génération, avant d'avoir postulé — on le retrouve par l'`offre.json` que
    chaque dossier archive : le nom du dossier dépend du jour et de l'intitulé
    nettoyé, il ne suffit pas à l'identifier.
    """
    candidature = session.exec(select(Application).where(Application.offer_id == offre.id)).first()
    if candidature and candidature.dossier_local and Path(candidature.dossier_local).is_dir():
        return Path(candidature.dossier_local)

    racine = reglages().chemins.candidatures
    trouves = []
    for archive in racine.glob("*/offre.json"):
        try:
            contenu = json.loads(archive.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if contenu.get("source") == offre.source and contenu.get("source_id") == offre.source_id:
            trouves.append(archive.parent)
    return max(trouves, key=lambda d: d.stat().st_mtime) if trouves else None


@router.get("/{offre_id}/documents")
def lister_documents(offre_id: int, session: Session = Depends(get_session)) -> dict:
    offre = session.get(Offer, offre_id)
    if offre is None:
        raise HTTPException(404, "Offre introuvable.")
    dossier = _dossier_de(offre, session)
    if dossier is None:
        return {"dossier": None, "fichiers": []}
    fichiers = sorted(
        ({"nom": f.name, "taille": f.stat().st_size} for f in dossier.iterdir()
         if f.is_file() and f.suffix.lower() in TELECHARGEABLES),
        # Les PDF d'abord : c'est ce qu'on envoie.
        key=lambda f: (not f["nom"].lower().endswith(".pdf"), f["nom"]))
    return {"dossier": dossier.name, "fichiers": fichiers}


@router.get("/{offre_id}/documents/{nom}")
def telecharger_document(offre_id: int, nom: str,
                         session: Session = Depends(get_session)) -> FileResponse:
    offre = session.get(Offer, offre_id)
    dossier = _dossier_de(offre, session) if offre else None
    # Un simple nom de fichier, d'un type attendu, présent dans CE dossier :
    # « ../../.env » ou « data/dreamjob.db » ne passent aucun des trois tests.
    if (dossier is None or nom != Path(nom).name
            or Path(nom).suffix.lower() not in TELECHARGEABLES):
        raise HTTPException(404, "Document introuvable.")
    chemin = dossier / nom
    if not chemin.is_file():
        raise HTTPException(404, "Document introuvable.")
    return FileResponse(chemin, filename=nom, media_type=TELECHARGEABLES[chemin.suffix.lower()])
