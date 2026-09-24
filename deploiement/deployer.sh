#!/usr/bin/env bash
# Envoie le code — et, au premier déploiement, tes données — sur le serveur,
# puis (re)construit et relance l'application. Depuis ton PC, dans Git Bash :
#
#     deploiement/deployer.sh dreamjob            # mise à jour du code seul
#     deploiement/deployer.sh dreamjob --donnees  # + base, modèle de CV, dossiers
#
# « dreamjob » est le nom du serveur sur ton réseau Tailscale ; son adresse IP
# fonctionne aussi. Rien ne passe par GitHub : le code part de ton PC.
#
# Le fichier .env n'est JAMAIS envoyé par ce script : les secrets se déposent à
# la main, une fois (voir GUIDE.md, étape 5).
set -euo pipefail

SERVEUR="${1:?Usage : deployer.sh <serveur> [--donnees]}"
DONNEES="${2:-}"
CIBLE="root@${SERVEUR}"
RACINE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RACINE"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Des modifications ne sont pas committées : c'est le dernier commit qui part." >&2
fi

echo "== Code (dernier commit : $(git log -1 --format='%h %s'))"
# `git archive` n'envoie que ce que git suit : ni .env, ni data/, ni node_modules.
git archive --format=tar HEAD | ssh "$CIBLE" "mkdir -p /opt/dreamjob && tar -x -C /opt/dreamjob"

if [[ "$DONNEES" == "--donnees" ]]; then
  echo "== Données (premier déploiement)"
  # La base est copiée depuis une sauvegarde cohérente, jamais en direct : en
  # WAL, le fichier seul serait amputé des écritures récentes.
  SAUVEGARDE="$(mktemp -d)/dreamjob.db"
  backend/.venv/Scripts/python.exe -c "
import sqlite3, sys
source = sqlite3.connect('data/dreamjob.db'); cible = sqlite3.connect(sys.argv[1])
source.backup(cible); cible.close(); source.close()" "$SAUVEGARDE"
  scp -q "$SAUVEGARDE" "$CIBLE:/opt/dreamjob/data/dreamjob.db"
  scp -q templates/cv_modele.docx "$CIBLE:/opt/dreamjob/templates/"
  if [[ -d "$HOME/Jobscout/candidatures" ]]; then
    tar -c -C "$HOME/Jobscout" candidatures | ssh "$CIBLE" "tar -x -C /opt/dreamjob"
  fi
  ssh "$CIBLE" "chown -R 1000:1000 /opt/dreamjob/data /opt/dreamjob/candidatures"
fi

echo "== Construction et redémarrage (quelques minutes la première fois)"
ssh "$CIBLE" "cd /opt/dreamjob && test -f .env || { echo 'Il manque /opt/dreamjob/.env : voir GUIDE.md, étape 5.' >&2; exit 1; }
cd /opt/dreamjob && docker compose up -d --build && docker compose ps"
