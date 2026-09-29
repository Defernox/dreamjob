#!/usr/bin/env bash
# Prépare un VPS Ubuntu 24.04 neuf pour DreamJob (OVHcloud VPS-1). À lancer UNE
# fois, depuis le compte « ubuntu » que livre OVH :
#
#     sudo bash installer-serveur.sh
#
# Installe Docker et Tailscale, ferme tout ce qui n'est pas nécessaire, n'admet
# plus que les connexions SSH par clé, crée /opt/dreamjob. Relançable sans
# danger : chaque étape vérifie avant d'agir.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "À lancer avec sudo : sudo bash installer-serveur.sh" >&2
  exit 1
fi
# Le compte qui a lancé sudo : c'est lui que deployer.sh utilisera.
COMPTE="${SUDO_USER:-root}"

echo "== 1/6  Connexion SSH par clé seulement"
# OVH livre le VPS avec un mot de passe : SSH restant ouvert sur Internet, il
# serait essayé en boucle par des robots. On ne coupe les mots de passe que si
# une clé est bien installée — sinon, on se fermerait la porte.
CLES="$(getent passwd "$COMPTE" | cut -d: -f6)/.ssh/authorized_keys"
if [[ -s "$CLES" ]] && grep -qE '^(ssh-|ecdsa-)' "$CLES"; then
  # Lu avant 50-cloud-init.conf, qui réactive les mots de passe : le premier
  # réglage rencontré l'emporte.
  printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n' \
    > /etc/ssh/sshd_config.d/10-dreamjob.conf
  systemctl reload ssh 2>/dev/null || systemctl restart ssh
  echo "   Mots de passe refusés ; seule ta clé ouvre le serveur."
else
  echo "   ATTENTION : aucune clé SSH pour $COMPTE ($CLES). Mots de passe laissés actifs :" >&2
  echo "   installe ta clé (GUIDE.md, étape 4) puis relance ce script." >&2
fi
# deployer.sh lance ses commandes par `sudo` sans terminal : le mot de passe
# ne peut pas y être demandé. Le compte, déjà administrateur, n'en aura plus
# besoin (c'est le réglage d'origine des images Ubuntu des hébergeurs).
if [[ "$COMPTE" != "root" ]]; then
  echo "$COMPTE ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-dreamjob
  chmod 440 /etc/sudoers.d/90-dreamjob
  visudo -cf /etc/sudoers.d/90-dreamjob >/dev/null
fi

echo "== 2/6  Mises à jour du système, et mises à jour de sécurité automatiques"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -yq
apt-get install -yq unattended-upgrades ufw curl ca-certificates
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "== 3/6  Docker"
if ! command -v docker >/dev/null; then
  apt-get install -yq docker.io docker-compose-v2
  systemctl enable --now docker
fi
docker --version

echo "== 4/6  Tailscale"
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

echo "== 5/6  Pare-feu : rien n'entre, sauf SSH et le réseau Tailscale"
# L'application n'écoute que sur 127.0.0.1 (docker-compose.yml) : même sans ce
# pare-feu, elle ne serait pas joignable depuis Internet. Le pare-feu ferme le
# reste — une seconde barrière, pas la seule.
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow in on tailscale0
ufw --force enable
ufw status verbose | head -12

echo "== 6/6  Dossier de l'application"
mkdir -p /opt/dreamjob/{data,templates,candidatures}
# UID 1000 : l'utilisateur non-root du conteneur (Dockerfile). Sans cela, il
# ne pourrait pas écrire dans les volumes créés par root.
chown -R 1000:1000 /opt/dreamjob/data /opt/dreamjob/candidatures

echo
echo "Serveur prêt pour le compte « $COMPTE ». Adresse Tailscale : $(tailscale ip -4 2>/dev/null || echo '?')"
echo "Étape suivante, depuis ton PC : deploiement/deployer.sh (voir GUIDE.md)."
