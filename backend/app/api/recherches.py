"""Les recherches enregistrées : ce que l'application ira chercher, et où."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..db import get_session
from ..models import Recherche
from ..models.base import maintenant
from ..schemas.recherche import RechercheEcriture, RechercheLecture, RechercheMaj

router = APIRouter(prefix="/api/recherches", tags=["recherches"])


@router.get("", response_model=list[RechercheLecture])
def lister(session: Session = Depends(get_session)) -> list[Recherche]:
    return list(session.exec(
        select(Recherche).order_by(Recherche.ordre, Recherche.id)
    ).all())


@router.post("", response_model=RechercheLecture, status_code=201)
def creer(
    ecriture: RechercheEcriture,
    session: Session = Depends(get_session),
) -> Recherche:
    recherche = Recherche(**ecriture.model_dump())
    session.add(recherche)
    try:
        session.commit()
    except IntegrityError as e:
        session.rollback()
        raise HTTPException(
            409, f"Une recherche nommée « {ecriture.nom} » existe déjà."
        ) from e
    session.refresh(recherche)
    return recherche


@router.patch("/{recherche_id}", response_model=RechercheLecture)
def modifier(
    recherche_id: int,
    maj: RechercheMaj,
    session: Session = Depends(get_session),
) -> Recherche:
    recherche = session.get(Recherche, recherche_id)
    if recherche is None:
        raise HTTPException(404, "Recherche introuvable.")

    for champ, valeur in maj.model_dump(exclude_unset=True).items():
        if valeur is not None:
            setattr(recherche, champ, valeur)
    recherche.updated_at = maintenant()
    session.add(recherche)
    try:
        session.commit()
    except IntegrityError as e:
        session.rollback()
        raise HTTPException(409, "Ce nom est déjà pris.") from e
    session.refresh(recherche)
    return recherche


@router.delete("/{recherche_id}", status_code=204)
def supprimer(recherche_id: int, session: Session = Depends(get_session)) -> None:
    recherche = session.get(Recherche, recherche_id)
    if recherche is None:
        raise HTTPException(404, "Recherche introuvable.")
    session.delete(recherche)
    session.commit()
