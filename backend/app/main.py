"""Point d'entrée de l'API DreamJob.

En local, l'API n'écoute que sur 127.0.0.1. Hébergée (`DREAMJOB_MODE=serveur`),
elle exige une connexion et sert elle-même l'interface compilée. Elle ne parle
qu'à SQLite, à l'API Anthropic et aux sources d'offres.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import acces, applications, documents, meta, offers, profile, recherches, scans
from .config import RACINE, reglages
from .db import checkpoint, creer_tables
from .services.sauvegarde import sauvegarder
from .scheduler import arreter as arreter_planificateur
from .scheduler import demarrer as demarrer_planificateur

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dreamjob")


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    r = reglages()
    for dossier in (r.chemins.dossier_cache, r.chemins.dossier_logs, r.chemins.candidatures):
        dossier.mkdir(parents=True, exist_ok=True)
    creer_tables()

    # Avant toute écriture : une copie datée de ce qui existe déjà.
    if r.sauvegardes.a_conserver > 0:
        sauvegarder(r.chemins.db, r.chemins.dossier_sauvegardes,
                    r.sauvegardes.a_conserver)

    log.info("Base      : %s", r.chemins.db)
    log.info("Dossiers  : %s", r.chemins.candidatures)
    if not r.llm_disponible:
        log.warning("ANTHROPIC_API_KEY absente — mode dégradé (scoring lexical, pas de lettre).")
    if not r.chemins.cv_modele.exists():
        log.warning("Modèle de CV absent : %s", r.chemins.cv_modele)
    actives = [k for k, s in r.sources.items() if s.actif]
    log.info("Sources actives : %s", ", ".join(actives) or "aucune")

    demarrer_planificateur()
    yield
    arreter_planificateur()
    # Le journal WAL rejoint le fichier principal : rien d'important ne reste
    # dans un fichier annexe une fois l'application fermée.
    checkpoint()
    log.info("Base consolidée, arrêt propre.")


app = FastAPI(
    title="DreamJob",
    description="Agrégation d'offres, scoring, génération de candidatures — 100 % local.",
    version="0.1.0",
    lifespan=cycle_de_vie,
)

# Le front Vite tourne sur 5173 ; rien d'autre n'a besoin d'accéder à l'API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Le verrou passe avant tout routeur : ce qui n'est pas explicitement ouvert
# est fermé dès que la connexion est requise (mode serveur).
app.middleware("http")(acces.verrou)

app.include_router(acces.router)
app.include_router(meta.router)
app.include_router(profile.router)
app.include_router(scans.router)
app.include_router(recherches.router)
app.include_router(offers.router)
app.include_router(applications.router)
app.include_router(documents.router)


# --- L'interface compilée, servie par l'API elle-même -------------------------
# En local, Vite sert l'interface sur 5173 et relaie /api. Sur le serveur, un
# seul processus sur un seul port : `npm run build` produit frontend/dist, que
# l'API sert directement — rien d'autre à installer ni à surveiller.
FRONT = RACINE / "frontend" / "dist"

if FRONT.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONT / "assets"), name="assets")

    @app.get("/{chemin:path}", include_in_schema=False)
    def interface(chemin: str) -> FileResponse:
        if chemin.startswith("api/"):
            raise HTTPException(404, "Route d'API inconnue.")
        fichier = (FRONT / chemin).resolve()
        # `resolve` puis vérification du parent : « ../../.env » ne sort pas du dossier.
        if chemin and fichier.is_file() and FRONT.resolve() in fichier.parents:
            return FileResponse(fichier)
        # Toute autre adresse est une page de l'application : c'est le routeur
        # du navigateur qui l'affiche.
        return FileResponse(FRONT / "index.html")
else:
    @app.get("/")
    def racine() -> dict:
        return {"application": "DreamJob", "documentation": "/docs", "sante": "/api/sante"}
