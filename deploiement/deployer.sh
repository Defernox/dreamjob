#!/usr/bin/env bash
# Envoie le code — et, au premier déploiement, tes données — sur le serveur,
# puis (re)construit et relance l'application. Depuis ton PC, dans Git Bash :
#
#     deploiement/deployer.sh dreamjob            # mise à jour du code seul
#     deploiement/deployer.sh dreamjob --donnees  # + base, modèle de CV, dossiers
#
# `--donnees` ne sert qu'au premier déploiement : si le serveur a déjà une base,
# il refuse — elle porte les comptes des amis, les candidatures, les notes, que
# celle du PC n'a pas. `--donnees --ecraser` la remplace quand même, après
# l'avoir mise de côté dans data/avant-ecrasement-<date>/.
#
# « dreamjob » est le nom du serveur sur ton réseau Tailscale ; son adresse IP
# fonctionne aussi. Rien ne passe par GitHub : le code part de ton PC.
#
# Le fichier .env n'est JAMAIS envoyé par ce script : les secrets se déposent à
# la main, une fois (voir GUIDE.md, étape 5).
set -euo pipefail

SERVEUR="${1:?Usage : deployer.sh <serveur> [--donnees [--ecraser]]}"
DONNEES="${2:-}"
ECRASER="${3:-}"
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
  if ssh "$CIBLE" "test -s /opt/dreamjob/data/dreamjob.db"; then
    if [[ "$ECRASER" != "--ecraser" ]]; then
      echo "Le serveur a déjà une base : --donnees ne sert qu'au premier déploiement." >&2
      echo "La remplacer par celle du PC ferait perdre ce qui n'existe que là-bas (comptes, candidatures)." >&2
      echo "Pour la remplacer quand même : deployer.sh $SERVEUR --donnees --ecraser" >&2
      exit 1
    fi
    echo "   (--ecraser : la base du serveur est mise de côté avant d'être remplacée)"
  fi
  # L'application s'arrête pendant la copie : une base ouverte en WAL ne se
  # remplace pas sous ses pieds — son journal annexe (-wal) serait rejoué sur
  # le nouveau fichier et le corromprait. Ce journal part avec l'ancienne base.
  ssh "$CIBLE" "cd /opt/dreamjob && { docker compose stop 2>/dev/null || true; } && cd data \
    && if ls dreamjob.db* >/dev/null 2>&1; then d=avant-ecrasement-\$(date +%Y%m%d-%H%M%S) \
         && mkdir -p \$d && mv dreamjob.db* \$d/ && echo \"   ancienne base : data/\$d\"; fi"
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
