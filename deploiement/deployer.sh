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
# fonctionne aussi. On s'y connecte avec le compte « ubuntu » que livre OVH ;
# un autre compte s'écrit en entier (`deployer.sh moi@dreamjob`). Toutes les
# commandes passent par sudo. Rien ne passe par GitHub : le code part de ton PC.
#
# Le fichier .env n'est JAMAIS envoyé par ce script : les secrets se déposent à
# la main, une fois (voir GUIDE.md, étape 6).
set -euo pipefail

SERVEUR="${1:?Usage : deployer.sh <serveur> [--donnees [--ecraser]]}"
DONNEES="${2:-}"
ECRASER="${3:-}"
if [[ "$SERVEUR" == *@* ]]; then CIBLE="$SERVEUR"; else CIBLE="ubuntu@${SERVEUR}"; fi
RACINE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RACINE"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Des modifications ne sont pas committées : c'est le dernier commit qui part." >&2
fi

# sudo sans mot de passe (installer-serveur.sh le règle) : sans terminal, il ne
# pourrait pas en demander un. Mieux vaut le dire tout de suite qu'à mi-chemin.
if ! ssh "$CIBLE" "sudo -n true" 2>/dev/null; then
  echo "Connexion à $CIBLE impossible, ou sudo y demande un mot de passe." >&2
  echo "As-tu lancé installer-serveur.sh (GUIDE.md, étape 5) ?" >&2
  exit 1
fi

echo "== Code (dernier commit : $(git log -1 --format='%h %s'))"
# `git archive` n'envoie que ce que git suit : ni .env, ni data/, ni node_modules.
git archive --format=tar HEAD | ssh "$CIBLE" "sudo mkdir -p /opt/dreamjob && sudo tar -x -C /opt/dreamjob"

if [[ "$DONNEES" == "--donnees" ]]; then
  echo "== Données (premier déploiement)"
  for requis in data/dreamjob.db templates/cv_modele.docx; do
    [[ -f "$requis" ]] || { echo "Introuvable sur ce PC : $requis" >&2; exit 1; }
  done
  if ssh "$CIBLE" "sudo test -s /opt/dreamjob/data/dreamjob.db"; then
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
  ssh "$CIBLE" "cd /opt/dreamjob && { sudo docker compose stop 2>/dev/null || true; } && cd data \
    && if ls dreamjob.db* >/dev/null 2>&1; then d=avant-ecrasement-\$(date +%Y%m%d-%H%M%S) \
         && sudo mkdir -p \$d && sudo mv dreamjob.db* \$d/ && echo \"   ancienne base : data/\$d\"; fi"
  # La base est copiée depuis une sauvegarde cohérente, jamais en direct : en
  # WAL, le fichier seul serait amputé des écritures récentes.
  SAUVEGARDE="$(mktemp -d)/dreamjob.db"
  backend/.venv/Scripts/python.exe -c "
import sqlite3, sys
source = sqlite3.connect('file:data/dreamjob.db?mode=ro', uri=True); cible = sqlite3.connect(sys.argv[1])
source.backup(cible); cible.close(); source.close()" "$SAUVEGARDE"
  # Écrits par `sudo tee` : /opt/dreamjob appartient à root, pas au compte ubuntu.
  ssh "$CIBLE" "sudo tee /opt/dreamjob/data/dreamjob.db >/dev/null" < "$SAUVEGARDE"
  ssh "$CIBLE" "sudo mkdir -p /opt/dreamjob/templates && sudo tee /opt/dreamjob/templates/cv_modele.docx >/dev/null" \
    < templates/cv_modele.docx
  if [[ -d "$HOME/Jobscout/candidatures" ]]; then
    tar -c -C "$HOME/Jobscout" candidatures | ssh "$CIBLE" "sudo tar -x -C /opt/dreamjob"
  fi
  ssh "$CIBLE" "sudo chown -R 1000:1000 /opt/dreamjob/data /opt/dreamjob/candidatures"
fi

echo "== Construction et redémarrage (quelques minutes la première fois)"
ssh "$CIBLE" "cd /opt/dreamjob && sudo test -f .env || { echo 'Il manque /opt/dreamjob/.env : voir GUIDE.md, étape 6.' >&2; exit 1; }
cd /opt/dreamjob && sudo docker compose up -d --build && sudo docker compose ps"
