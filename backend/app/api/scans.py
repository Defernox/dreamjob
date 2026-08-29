"""Lancer une recherche, et consulter l'historique des scans."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, desc, select

from ..config import reglages
from ..connectors.registry import cles_actives
from ..db import get_session
from ..connectors.base import SearchQuery
from ..models import ScanRun
from ..schemas.scan import RequeteScan, ScanLecture
from ..services.scan import lancer_scan, requete_par_defaut, requetes_actives

router = APIRouter(prefix="/api/scans", tags=["scans"])


def _construire_requete(
    demande: RequeteScan | None, session: Session
) -> SearchQuery | list[SearchQuery]:
    """Ce que le scan va chercher.

    Sans surcharge de l'interface, on joue les recherches enregistrées — c'est
    le cas courant. Une demande explicite les remplace, pour permettre un scan
    ponctuel sur d'autres mots-clés sans toucher aux recherches.
    """
    if demande is None or not demande.model_dump(exclude_unset=True):
        return requetes_actives(session, reglages())

    base = requete_par_defaut(reglages())
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
) -> ScanRun:
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
    return lancer_scan(session, _construire_requete(demande, session), sources=sources)


@router.get("/planification")
def planification() -> dict:
    """État du scan automatique, pour l'afficher dans l'interface."""
    from ..scheduler import etat

    return etat()


@router.get("", response_model=list[ScanLecture])
def historique(limite: int = 20, session: Session = Depends(get_session)) -> list[ScanRun]:
    return list(session.exec(
        select(ScanRun).order_by(desc(ScanRun.started_at)).limit(limite)
    ).all())


@router.get("/{scan_id}", response_model=ScanLecture)
def detail(scan_id: int, session: Session = Depends(get_session)) -> ScanRun:
    scan = session.get(ScanRun, scan_id)
    if scan is None:
        raise HTTPException(404, "Scan introuvable.")
    return scan
