# DreamJob hébergé : l'API sert elle-même l'interface compilée, sur un seul port.
# Construite sur le serveur (docker compose up -d --build) — voir deploiement/GUIDE.md.

# --- 1. L'interface ------------------------------------------------------------
FROM node:22-slim AS interface
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# `npm run build` lance `tsc -b` : une erreur de typage fait échouer l'image au
# lieu de passer en production.
RUN npm run build

# --- 2. L'application ----------------------------------------------------------
FROM python:3.14-slim

# LibreOffice sans interface, pour convertir CV et lettre en PDF.
# Carlito a les MÊMES métriques que Calibri, seule police du modèle de CV et de
# la lettre : sans elle, LibreOffice en substitue une autre, les lignes changent
# de longueur, et le CV qui tenait sur une page sous Windows en fait deux ici.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libreoffice-writer-nogui fonts-crosextra-carlito fonts-crosextra-caladea \
      fonts-liberation fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

# Jamais root : le conteneur n'a besoin d'écrire que dans ses volumes.
RUN useradd --create-home --uid 1000 dreamjob
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY config.yaml employeurs.yaml ./
COPY --from=interface /src/frontend/dist frontend/dist
RUN mkdir -p data templates /home/dreamjob/Jobscout/candidatures \
 && chown -R dreamjob:dreamjob /app/data /home/dreamjob

# Le mode serveur : connexion obligatoire, cookies HTTPS, pas d'ouverture de
# dossier. Fixé dans l'image, pas dans un fichier de réglages : un conteneur
# lancé sans lui serait ouvert à qui connaît son adresse.
ENV DREAMJOB_MODE=serveur \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER dreamjob
WORKDIR /app/backend
EXPOSE 8000

# Les migrations d'abord, à chaque démarrage : une mise à jour du code qui
# apporte une colonne l'applique d'elle-même.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*"]
