# Mettre DreamJob en ligne

Résultat : DreamJob tourne 24 h/24 sur un petit serveur, joignable **uniquement**
depuis tes appareils (PC, téléphone) grâce à Tailscale, derrière un mot de passe.
Le scan part chaque matin à 7 h 30 et t'envoie les nouvelles offres vertes sur
ton téléphone.

Coût : ~7 €/mois (serveur Hetzner CX23), + ~1,40 € si tu actives les sauvegardes
Hetzner (recommandé). Tailscale et ntfy sont gratuits.

Compte une heure la première fois. Les étapes marquées **(toi)** demandent de
créer un compte, de payer ou de saisir un mot de passe : c'est à toi de les faire.

---

## 1. Tailscale (toi) — 5 min

1. Crée un compte sur https://tailscale.com (gratuit en usage personnel).
2. Installe Tailscale **sur ton PC** et **sur ton téléphone**, connecte-les à ce compte.
3. Dans la console Tailscale → **DNS** : active **MagicDNS** et **HTTPS Certificates**.

## 2. Une clé SSH sur ton PC (toi) — 2 min

Dans Git Bash :

```bash
ssh-keygen -t ed25519 -C "dreamjob"
```

Garde le chemin proposé ; choisis une phrase de passe. Puis affiche la clé
**publique** (celle qui finit par `.pub`, jamais l'autre) :

```bash
cat ~/.ssh/id_ed25519.pub
```

## 3. Le serveur Hetzner (toi) — 10 min

1. Crée un compte sur https://console.hetzner.com et ajoute un moyen de paiement.
2. **Nouveau serveur** : Ubuntu 24.04 · type **CX23** · Allemagne (Nuremberg ou
   Falkenstein) · colle ta clé **publique** dans « SSH keys » · coche
   **Backups** (recommandé).
3. Note l'adresse IP du serveur.

## 4. Préparer le serveur — 5 min

Depuis Git Bash, à la racine du projet (remplace `IP` par l'adresse du serveur) :

```bash
scp deploiement/installer-serveur.sh root@IP:
```

```bash
ssh root@IP bash installer-serveur.sh
```

Le script affiche un lien Tailscale : ouvre-le et valide avec ton compte. Le
serveur apparaît alors sous le nom **dreamjob** dans ton réseau Tailscale.

## 5. Les secrets (toi) — 2 min

Ton `.env` local contient déjà les clés. Copie-le sur le serveur :

```bash
scp .env root@dreamjob:/opt/dreamjob/.env
```

Puis ajoute les deux lignes propres au serveur :

```bash
ssh root@dreamjob
```

```bash
nano /opt/dreamjob/.env
```

```
DREAMJOB_URL=https://dreamjob.TON-RESEAU.ts.net
NTFY_SUJET=une-suite-longue-et-imprevisible-de-mots
```

`TON-RESEAU` : le nom de ton réseau, visible dans la console Tailscale (DNS).
`NTFY_SUJET` : invente-le long, il sert de mot de passe aux notifications.

## 6. Déployer — 10 min la première fois

Depuis ton PC, à la racine du projet :

```bash
deploiement/deployer.sh dreamjob --donnees
```

Cela envoie le code, ta base (offres, profil, candidatures), ton modèle de CV et
tes dossiers de candidature, puis construit et démarre l'application.

## 7. Ton compte (toi) — 1 min

```bash
ssh -t root@dreamjob "cd /opt/dreamjob && docker compose exec dreamjob python -m app.compte creer ton@email.fr"
```

Tu saisis le mot de passe au clavier (12 caractères minimum) : il n'apparaît
nulle part.

## 8. Ouvrir l'accès HTTPS — 1 min

```bash
ssh root@dreamjob tailscale serve --bg 8000
```

DreamJob est maintenant sur **https://dreamjob.TON-RESEAU.ts.net**, depuis ton PC
comme depuis ton téléphone — et nulle part ailleurs.

## 9. Les notifications sur ton téléphone (toi) — 2 min

Installe l'application **ntfy** et abonne-toi au sujet choisi à l'étape 5.

---

## Ensuite

| Pour… | Commande (Git Bash, racine du projet) |
|---|---|
| Mettre à jour le code | `deploiement/deployer.sh dreamjob` |
| Voir les journaux | `ssh root@dreamjob "cd /opt/dreamjob && docker compose logs --tail 100"` |
| Changer ton mot de passe | `ssh -t root@dreamjob "cd /opt/dreamjob && docker compose exec dreamjob python -m app.compte mot-de-passe ton@email.fr"` |
| Ajouter un ami (plus tard) | lui créer un compte (étape 7) et l'inviter dans ton réseau Tailscale |

**Ta machine locale** continue de fonctionner comme avant, avec sa propre base.
Une fois le serveur en place, c'est lui qui fait foi : évite de postuler depuis
les deux, les candidatures ne se synchronisent pas.
