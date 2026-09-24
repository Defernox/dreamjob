"""Lancer une recherche, et consulter l'historique des scans."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, desc, select

from ..config import reglages
from ..connectors.registry import cles_actives
from ..db import get_session
from ..connectors.base import SearchQuery
from ..models import ScanRun, Utilisateur
from ..schemas.scan import RequeteScan, ScanLecture
from ..services.scan import (
    lancer_scan,
    requete_depuis_profil,
    requete_par_defaut,
    requetes_actives,
)
from .acces import utilisateur_courant

router = APIRouter(prefix="/api/scans", tags=["scans"])


def _construire_requete(
    demande: RequeteScan | None, session: Session, moi: Utilisateur
) -> SearchQuery | list[SearchQuery]:
    """Ce que le scan va chercher.

    Sans surcharge de l'interface, on joue les recherches enregistrées du
    compte — c'est le cas courant. Une demande explicite les remplace, pour
    permettre un scan ponctuel sur d'autres mots-clés sans toucher aux
    recherches.
    """
    if demande is None or not demande.model_dump(exclude_unset=True):
        return requetes_actives(session, reglages(), moi.id)

    # config.yaml porte la recherche du propriétaire : un autre compte complète
    # sa demande avec son propre profil.
    base = (requete_par_defaut(reglages()) if moi.proprietaire
            else requete_depuis_profil(session, reglages(), moi.id))
    return SearchQuery(
        mots_cles=demande.mots_cles if demande.mots_cles is not None else base.mots_cles,
        pays=demande.pays if demande.pays is not None else base.pays,
        contrats=demande.contrats if demande.contrats is not None else base.contrats,
        departement=demande.departement or base.departement,
        publiee_depuis_jours=demande.publiee_depuis_jours or base.publiee_depuis_jours,
        max_offres=demande.max_offres or base.max_offres,
    )


@router.post("", response_model=ScanLecture)
def lancer(
    demande: RequeteScan | None = None,
    session: Session = Depends(get_session),
    moi: Utilisateur = Depends(utilisateur_courant),
) -> ScanLecture:
    """Interroge les sources actives. Synchrone : un scan dure quelques secondes."""
    # `sources` absent => les sources actives de config.yaml.
    # `sources: []` => demande vide, sans doute une erreur : on le dit.
    sources = demande.sources if demande else None
    if sources == []:
        raise HTTPException(400, "Indiquez au moins une source, ou omettez le champ "
                                 "« sources » pour interroger toutes les sources actives.")
    if sources is None and not cles_actives(reglages()):
        raise HTTPException(
            409,
            "Aucune source active. Activez-en une dans config.yaml et renseignez "
            "ses identifiants dans .env.",
        )
    requete = _construire_requete(demande, session, moi)
    if requete == []:
        raise HTTPException(
            409, "Rien à chercher : enregistrez une recherche, ou renseignez le "
                 "titre visé de votre profil.")
    return _en_lecture(lancer_scan(session, requete, sources=sources, utilisateur_id=moi.id),
                       moi)


@router.get("/planification")
def planification(moi: Utilisateur = Depends(utilisateur_courant)) -> dict:
    """État du scan automatique, pour l'afficher dans l'interface."""
    from ..scheduler import etat

    return etat(moi.id)


def _en_lecture(scan: ScanRun, moi: Utilisateur) -> ScanLecture:
    """Le scan tel que le compte peut le voir. Les mots-clés d'un scan qu'il n'a
    pas lancé — le planifié réunit ceux de tous les comptes — ne sont pas les
    siens : ils ne lui sont pas montrés."""
    lecture = ScanLecture.model_validate(scan.model_dump())
    if scan.utilisateur_id != moi.id:
        lecture.requete = {}
    return lecture


@router.get("", response_model=list[ScanLecture])
def historique(limite: int = 20, session: Session = Depends(get_session),
               moi: Utilisateur = Depends(utilisateur_courant)) -> list[ScanLecture]:
    scans = session.exec(
        select(ScanRun)
        .where(ScanRun.utilisateur_id.is_(None) | (ScanRun.utilisateur_id == moi.id))
        .order_by(desc(ScanRun.started_at)).limit(limite)
    ).all()
    return [_en_lecture(scan, moi) for scan in scans]


@router.get("/{scan_id}", response_model=ScanLecture)
def detail(scan_id: int, session: Session = Depends(get_session),
           moi: Utilisateur = Depends(utilisateur_courant)) -> ScanLecture:
    scan = session.get(ScanRun, scan_id)
    if scan is None or scan.utilisateur_id not in (None, moi.id):
        raise HTTPException(404, "Scan introuvable.")
    return _en_lecture(scan, moi)
