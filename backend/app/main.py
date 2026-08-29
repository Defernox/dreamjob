"""Point d'entrée de l'API DreamJob.

Application locale, mono-utilisateur : l'API n'écoute que sur 127.0.0.1 et ne
parle qu'à SQLite, à l'API Anthropic et aux sources d'offres.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import applications, documents, meta, offers, profile, scans
from .config import reglages
from .db import checkpoint, creer_tables
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

app.include_router(meta.router)
app.include_router(profile.router)
app.include_router(scans.router)
app.include_router(offers.router)
app.include_router(applications.router)
app.include_router(documents.router)


@app.get("/")
def racine() -> dict:
    return {"application": "DreamJob", "documentation": "/docs", "sante": "/api/sante"}
