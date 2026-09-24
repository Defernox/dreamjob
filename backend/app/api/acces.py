"""Connexion, déconnexion, état — et le verrou qui protège le reste de l'API.

Il n'y a **pas d'inscription** par l'API : un compte se crée sur le serveur, en
ligne de commande (`python -m app.compte`). Une page d'inscription serait une
porte ouverte à quiconque trouve l'adresse ; ici, seul celui qui a la main sur
la machine décide qui entre.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import Session

from ..config import reglages
from ..db import get_session
from ..services.acces import (
    COOKIE,
    DUREE_SESSION,
    authentifier,
    fermer_session,
    limiteur,
    ouvrir_session,
    utilisateur_de,
)

router = APIRouter(prefix="/api/acces", tags=["accès"])

# Ce qui reste joignable sans session : de quoi se connecter, et de quoi savoir
# si le serveur est vivant.
CHEMINS_OUVERTS = ("/api/acces/", "/api/sante")


class Identifiants(BaseModel):
    email: str
    mot_de_passe: str


def _adresse(request: Request) -> str:
    """L'adresse du client. Derrière `tailscale serve`, toutes les requêtes
    arrivent de 127.0.0.1 : on prend alors le premier maillon transmis."""
    transmise = request.headers.get("x-forwarded-for", "")
    return transmise.split(",")[0].strip() or (request.client.host if request.client else "?")


@router.get("/etat")
def etat(request: Request, session: Session = Depends(get_session)) -> dict:
    """Ce que l'interface doit afficher : l'application, ou l'écran de connexion."""
    requise = reglages().connexion_requise
    utilisateur = utilisateur_de(session, request.cookies.get(COOKIE)) if requise else None
    return {"connexion_requise": requise,
            "connecte": (not requise) or utilisateur is not None,
            "email": utilisateur.email if utilisateur else None}


@router.post("/connexion")
def connexion(identifiants: Identifiants, request: Request, response: Response,
              session: Session = Depends(get_session)) -> dict:
    adresse = _adresse(request)
    if limiteur.bloque(adresse):
        raise HTTPException(429, "Trop d'essais : réessayez dans un quart d'heure.")
    utilisateur = authentifier(session, identifiants.email, identifiants.mot_de_passe)
    if utilisateur is None:
        limiteur.echec(adresse)
        # Un seul message pour les deux cas : dire « adresse inconnue » révélerait
        # quels comptes existent.
        raise HTTPException(401, "Adresse ou mot de passe incorrect.")
    limiteur.reussite(adresse)
    response.set_cookie(
        COOKIE, ouvrir_session(session, utilisateur),
        max_age=int(DUREE_SESSION.total_seconds()),
        httponly=True,                       # illisible par le JavaScript de la page
        samesite="lax",                      # pas envoyé par un formulaire d'un autre site
        secure=reglages().serveur,           # HTTPS seulement, sur le serveur
    )
    return {"email": utilisateur.email}


@router.post("/deconnexion")
def deconnexion(request: Request, response: Response,
                session: Session = Depends(get_session)) -> dict:
    fermer_session(session, request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE)
    return {"deconnecte": True}


async def verrou(request: Request, call_next):
    """Refuse toute requête `/api/` sans session valide, quand la connexion est requise.

    Un intergiciel plutôt qu'une dépendance ajoutée à chaque routeur : une route
    oubliée serait une route ouverte. Ici, tout ce qui n'est pas explicitement
    ouvert est fermé.
    """
    chemin = request.url.path
    if (not reglages().connexion_requise or not chemin.startswith("/api/")
            or chemin.startswith(CHEMINS_OUVERTS)):
        return await call_next(request)

    # La même fabrique de sessions que les routes — surchargée par les tests.
    fabrique = request.app.dependency_overrides.get(get_session, get_session)
    generateur = fabrique()
    try:
        utilisateur = utilisateur_de(next(generateur), request.cookies.get(COOKIE))
    finally:
        generateur.close()
    if utilisateur is None:
        return JSONResponse({"detail": "Connexion requise."}, status_code=401)
    return await call_next(request)
