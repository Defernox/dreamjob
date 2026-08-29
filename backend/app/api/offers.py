"""Les offres : liste filtrée, détail, et déclenchement du scoring."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from ..config import reglages
from ..db import get_session
from ..models import Application, Offer, ScanRun
from ..models.base import maintenant
from ..schemas.offre import (
    Compteurs,
    OffreDetail,
    OffreResume,
    PageOffres,
    ResultatScoring,
    Statistiques,
)
from ..services.scan import dernier_scan_abouti
from ..services.scoring import ProfilVide, scorer_toutes

router = APIRouter(prefix="/api/offres", tags=["offres"])

TRIS = {
    # « Pertinence » : le meilleur score d'abord, la plus fraîche pour départager.
    "pertinence": (Offer.score.desc().nulls_last(), Offer.date_publication.desc().nulls_last()),
    "score": (Offer.score.desc().nulls_last(),),
    "recentes": (Offer.date_publication.desc().nulls_last(),),
    "anciennes": (Offer.date_publication.asc().nulls_last(),),
}


def _filtres(contrats, sources, pays, score_min, recherche, *, sauf: str = "") -> list:
    """Conditions SQL. `sauf` retire une facette, pour compter ses propres options."""
    conditions = []
    if contrats and sauf != "contrat":
        conditions.append(Offer.type_contrat.in_(contrats))
    if sources and sauf != "source":
        conditions.append(Offer.source.in_(sources))
    if pays and sauf != "pays":
        conditions.append(Offer.pays.in_(pays))
    if score_min is not None:
        conditions.append(Offer.score >= score_min)
    if recherche:
        motif = f"%{recherche}%"
        conditions.append(
            Offer.titre.ilike(motif) | Offer.entreprise.ilike(motif)
            | Offer.description_brute.ilike(motif)
        )
    return conditions


def _compter(session: Session, colonne, conditions) -> dict[str, int]:
    requete = select(colonne, func.count()).group_by(colonne)
    for condition in conditions:
        requete = requete.where(condition)
    return {valeur: nombre for valeur, nombre in session.exec(requete).all() if valeur}


@router.get("", response_model=PageOffres)
def lister(
    contrats: list[str] | None = Query(None),
    sources: list[str] | None = Query(None),
    pays: list[str] | None = Query(None),
    score_min: float | None = Query(None, ge=0, le=100),
    recherche: str | None = None,
    tri: str = "pertinence",
    limite: int = Query(60, ge=1, le=300),
    decalage: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> PageOffres:
    if tri not in TRIS:
        raise HTTPException(400, f"Tri inconnu. Valeurs possibles : {', '.join(TRIS)}")

    conditions = _filtres(contrats, sources, pays, score_min, recherche)

    requete = select(Offer)
    for condition in conditions:
        requete = requete.where(condition)
    total = session.exec(
        select(func.count()).select_from(Offer).where(*conditions) if conditions
        else select(func.count()).select_from(Offer)
    ).one()

    offres = list(session.exec(
        requete.order_by(*TRIS[tri]).offset(decalage).limit(limite)
    ).all())

    candidatures = set(session.exec(select(Application.offer_id)).all())

    return PageOffres(
        total=total,
        offres=[
            OffreResume(**o.model_dump(), a_candidature=o.id in candidatures) for o in offres
        ],
        compteurs=Compteurs(
            contrat=_compter(session, Offer.type_contrat,
                             _filtres(contrats, sources, pays, score_min, recherche, sauf="contrat")),
            source=_compter(session, Offer.source,
                            _filtres(contrats, sources, pays, score_min, recherche, sauf="source")),
            pays=_compter(session, Offer.pays,
                          _filtres(contrats, sources, pays, score_min, recherche, sauf="pays")),
        ),
    )


@router.get("/statistiques", response_model=Statistiques)
def statistiques(session: Session = Depends(get_session)) -> Statistiques:
    debut_journee = maintenant().replace(hour=0, minute=0, second=0, microsecond=0)

    def compter(*conditions):
        return session.exec(select(func.count()).select_from(Offer).where(*conditions)).one()

    scan = dernier_scan_abouti(session)

    # « Nouvelles » = arrivées à la dernière recherche et pas encore ouvertes.
    # Compter toutes les offres jamais ouvertes donnerait un badge bloqué à
    # « 99+ » pendant des mois : le signal « il y a du neuf » s'y perdrait.
    nouvelles = compter(
        Offer.vue == False,  # noqa: E712 — SQLAlchemy exige ==
        Offer.date_recuperation >= scan.started_at,
    ) if scan is not None else 0

    return Statistiques(
        total=session.exec(select(func.count()).select_from(Offer)).one(),
        aujourd_hui=compter(Offer.date_publication >= debut_journee),
        vie=compter(Offer.type_contrat == "V.I.E"),
        nouvelles=nouvelles,
        jamais_vues=compter(Offer.vue == False),  # noqa: E712
        non_scorees=compter(Offer.score.is_(None)),
        dernier_scan=scan.finished_at if scan else None,
    )


@router.post("/scorer", response_model=ResultatScoring)
def scorer(forcer: bool = False, session: Session = Depends(get_session)) -> dict:
    """Recalcule les scores. Aucun appel LLM : c'est du code pur."""
    try:
        return scorer_toutes(session, forcer=forcer)
    except ProfilVide as e:
        raise HTTPException(409, str(e)) from e


@router.get("/{offre_id}", response_model=OffreDetail)
def detail(offre_id: int, session: Session = Depends(get_session)) -> OffreDetail:
    offre = session.get(Offer, offre_id)
    if offre is None:
        raise HTTPException(404, "Offre introuvable.")
    if not offre.vue:
        offre.vue = True          # consulter une offre la retire du badge « nouvelles »
        session.add(offre)
        session.commit()
        session.refresh(offre)
    candidature = session.exec(
        select(Application).where(Application.offer_id == offre_id)
    ).first()
    return OffreDetail(**offre.model_dump(), a_candidature=candidature is not None)
