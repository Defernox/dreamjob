"""Les recherches enregistrées : ce que l'application ira chercher, et où."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..db import get_session
from ..models import Recherche, Utilisateur
from ..models.base import maintenant
from ..schemas.recherche import RechercheEcriture, RechercheLecture, RechercheMaj
from ..services.scoring import rescorer
from .acces import utilisateur_courant

# Les recherches disent ce que le candidat vise : elles entrent dans le score.
# Chaque changement relance le calcul, après la réponse.

router = APIRouter(prefix="/api/recherches", tags=["recherches"])


def _la_mienne(session: Session, recherche_id: int, utilisateur_id: int) -> Recherche:
    recherche = session.get(Recherche, recherche_id)
    if recherche is None or recherche.utilisateur_id != utilisateur_id:
        raise HTTPException(404, "Recherche introuvable.")
    return recherche


@router.get("", response_model=list[RechercheLecture])
def lister(session: Session = Depends(get_session),
           moi: Utilisateur = Depends(utilisateur_courant)) -> list[Recherche]:
    return list(session.exec(
        select(Recherche).where(Recherche.utilisateur_id == moi.id)
        .order_by(Recherche.ordre, Recherche.id)
    ).all())


@router.post("", response_model=RechercheLecture, status_code=201)
def creer(
    ecriture: RechercheEcriture,
    taches: BackgroundTasks,
    session: Session = Depends(get_session),
    moi: Utilisateur = Depends(utilisateur_courant),
) -> Recherche:
    taches.add_task(rescorer, session.get_bind(), moi.id)
    recherche = Recherche(**ecriture.model_dump(), utilisateur_id=moi.id)
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
    taches: BackgroundTasks,
    session: Session = Depends(get_session),
    moi: Utilisateur = Depends(utilisateur_courant),
) -> Recherche:
    recherche = _la_mienne(session, recherche_id, moi.id)
    taches.add_task(rescorer, session.get_bind(), moi.id)

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
def supprimer(recherche_id: int, taches: BackgroundTasks,
              session: Session = Depends(get_session),
              moi: Utilisateur = Depends(utilisateur_courant)) -> None:
    recherche = _la_mienne(session, recherche_id, moi.id)
    taches.add_task(rescorer, session.get_bind(), moi.id)
    session.delete(recherche)
    session.commit()
