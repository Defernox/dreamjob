"""Lancer une recherche, et consulter l'historique des scans."""

from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, desc, select

from ..config import reglages
from ..connectors.registry import cles_actives
from ..db import get_session
from ..connectors.base import SearchQuery
from ..models import ScanRun, Utilisateur
from ..models.enums import StatutScan
from ..scheduler import executer_scan_manuel
from ..schemas.scan import RequeteScan, ScanLecture
from ..services.scan import (
    requete_depuis_profil,
    requete_par_defaut,
    requetes_actives,
)
from ..services.veille import DECLENCHEUR as VEILLE
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


def _demarrer(cible, *arguments) -> None:
    """La recherche part dans son propre fil ; l'interface suit le scan « en
    cours » (`GET /api/scans/{id}`). Les tests la déroulent sur place."""
    threading.Thread(target=cible, args=arguments, name="recherche-manuelle", daemon=True).start()


@router.post("", response_model=ScanLecture)
def lancer(
    demande: RequeteScan | None = None,
    session: Session = Depends(get_session),
    moi: Utilisateur = Depends(utilisateur_courant),
) -> ScanLecture:
    """Lance une recherche sur les sources actives, en arrière-plan.

    Elle dure plusieurs minutes depuis que les sites des employeurs en font
    partie : attendue dans la requête, elle serait coupée par le relais HTTPS.
    La réponse est le scan « en cours » ; l'interface le relit jusqu'à la fin."""
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
    en_cours = session.exec(select(ScanRun).where(
        ScanRun.utilisateur_id == moi.id, ScanRun.statut == StatutScan.EN_COURS.value)).first()
    if en_cours is not None:
        raise HTTPException(409, "Une recherche est déjà en cours : elle se termine avant d'en lancer une autre.")
    scan = ScanRun(declenche_par="manuel", utilisateur_id=moi.id,
                   sources=sources if sources is not None else cles_actives(reglages()))
    session.add(scan)
    session.commit()
    session.refresh(scan)
    # Le scan note ses nouvelles offres dans la foulée : un scan manuel les
    # laissait sans note jusqu'au prochain clic sur « Scorer ».
    _demarrer(executer_scan_manuel, session.get_bind(), scan.id, requete, sources, moi.id)
    session.refresh(scan)
    return _en_lecture(scan, moi)


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
def historique(limite: int = 20, avec_veille: bool = True, session: Session = Depends(get_session),
               moi: Utilisateur = Depends(utilisateur_courant)) -> list[ScanLecture]:
    """`avec_veille=false` : les seules recherches. Une passe de veille toutes
    les demi-heures masquerait sinon le scan du matin dans le diagnostic, et
    l'écran Offres la prendrait pour une recherche de l'utilisateur."""
    requete = select(ScanRun).where(ScanRun.utilisateur_id.is_(None) | (ScanRun.utilisateur_id == moi.id))
    if not avec_veille:
        requete = requete.where(ScanRun.declenche_par != VEILLE)
    scans = session.exec(requete.order_by(desc(ScanRun.started_at)).limit(limite)).all()
    return [_en_lecture(scan, moi) for scan in scans]


@router.get("/{scan_id}", response_model=ScanLecture)
def detail(scan_id: int, session: Session = Depends(get_session),
           moi: Utilisateur = Depends(utilisateur_courant)) -> ScanLecture:
    scan = session.get(ScanRun, scan_id)
    if scan is None or scan.utilisateur_id not in (None, moi.id):
        raise HTTPException(404, "Scan introuvable.")
    return _en_lecture(scan, moi)
