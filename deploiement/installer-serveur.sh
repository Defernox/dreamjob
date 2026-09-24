#!/usr/bin/env bash
# Prépare un VPS Ubuntu 24.04 neuf pour DreamJob. À lancer UNE fois, en root :
#
#     bash installer-serveur.sh
#
# Installe Docker et Tailscale, ferme tout ce qui n'est pas nécessaire, crée
# /opt/dreamjob. Relançable sans danger : chaque étape vérifie avant d'agir.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "À lancer en root (ou avec sudo)." >&2
  exit 1
fi

echo "== 1/5  Mises à jour du système, et mises à jour de sécurité automatiques"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -yq
apt-get install -yq unattended-upgrades ufw curl ca-certificates
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "== 2/5  Docker"
if ! command -v docker >/dev/null; then
  apt-get install -yq docker.io docker-compose-v2
  systemctl enable --now docker
fi
docker --version

echo "== 3/5  Tailscale"
if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
if ! tailscale status >/dev/null 2>&1; then
  echo
  echo "   Tailscale va afficher un lien : ouvre-le et connecte-toi avec TON compte"
  echo "   Tailscale. Le serveur rejoindra ton réseau privé sous le nom « dreamjob »."
  echo
  tailscale up --hostname=dreamjob
fi
tailscale status | head -5

echo "== 4/5  Pare-feu : rien n'entre, sauf SSH et le réseau Tailscale"
# L'application n'écoute que sur 127.0.0.1 (docker-compose.yml) : même sans ce
# pare-feu, elle ne serait pas joignable depuis Internet. Le pare-feu ferme le
# reste — une seconde barrière, pas la seule.
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow in on tailscale0
ufw --force enable
ufw status verbose | head -12

echo "== 5/5  Dossier de l'application"
mkdir -p /opt/dreamjob/{data,templates,candidatures}
# UID 1000 : l'utilisateur non-root du conteneur (Dockerfile). Sans cela, il
# ne pourrait pas écrire dans les volumes créés par root.
chown -R 1000:1000 /opt/dreamjob/data /opt/dreamjob/candidatures

echo
echo "Serveur prêt. Adresse Tailscale : $(tailscale ip -4 2>/dev/null || echo '?')"
echo "Étape suivante, depuis ton PC : deploiement/deployer.sh (voir GUIDE.md)."
