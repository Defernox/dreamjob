# Mettre DreamJob en ligne

Résultat : DreamJob tourne 24 h/24 sur un petit serveur, joignable **uniquement**
depuis tes appareils (PC, téléphone) grâce à Tailscale, derrière un mot de passe.
Le scan part chaque matin à 7 h 30 et t'envoie les nouvelles offres vertes sur
ton téléphone.

Coût : **4,49 € HT/mois (≈ 5,39 € TTC)** pour un VPS-1 d'OVHcloud sans
engagement — 3,81 € HT (≈ 4,57 € TTC) en payant l'année d'avance —, sauvegarde
quotidienne et trafic illimité compris. Tarifs relevés le 2026-09-29. Tailscale
et ntfy sont gratuits.

Pourquoi OVH : Hetzner, d'abord prévu, n'avait plus de petit serveur disponible
le 2026-09-29 ; le VPS-1 a la même taille (2 cœurs, 4 Go, 40 Go), coûte moins,
et tourne **en France** (Gravelines) — ce que certains sites d'employeurs
regardent pour choisir les offres qu'ils montrent (HSBC).

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

## 3. Le serveur OVHcloud (toi) — 10 min

1. Crée un compte sur https://www.ovhcloud.com/fr/ et ajoute un moyen de paiement.
2. Commande un **VPS-1** depuis https://www.ovhcloud.com/fr/vps/ → *Configurer* :
   - **Période d'engagement** : *Aucun engagement* (ou *12 mois*, 15 % moins
     cher, renouvelé automatiquement — désactivable dans l'espace client) ;
   - **Localisation** : *Europe (France - Gravelines)* ;
   - **Image** : *Distribution uniquement* → **Ubuntu 24.04** (pas 26.04 : les
     scripts ont été écrits pour la 24.04) ;
   - **Options** : aucune. La sauvegarde quotidienne est déjà incluse.
3. OVH t'envoie par e-mail l'**adresse IP** du serveur, l'utilisateur
   **ubuntu** et de quoi obtenir son mot de passe. Garde ce message.

## 4. Ta clé sur le serveur (toi) — 2 min

Depuis Git Bash (remplace `IP` par l'adresse du serveur). Le mot de passe
d'OVH est demandé une dernière fois : ensuite, seule ta clé ouvrira le serveur.

```bash
cat ~/.ssh/id_ed25519.pub | ssh ubuntu@IP "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

Si le serveur exige de changer le mot de passe à la première connexion,
connecte-toi d'abord avec `ssh ubuntu@IP`, change-le, puis relance la commande.

## 5. Préparer le serveur — 5 min

Toujours depuis Git Bash, à la racine du projet :

```bash
scp deploiement/installer-serveur.sh ubuntu@IP:
```

```bash
ssh -t ubuntu@IP sudo bash installer-serveur.sh
```

Le script ferme la connexion par mot de passe (ta clé suffit), installe Docker
et Tailscale, et ferme le pare-feu. Il affiche un lien Tailscale : ouvre-le et
valide avec ton compte. Le serveur apparaît alors sous le nom **dreamjob** dans
ton réseau Tailscale.

## 6. Les secrets (toi) — 2 min

Ton `.env` local contient déjà les clés. Copie-le sur le serveur :

```bash
ssh ubuntu@dreamjob "sudo tee /opt/dreamjob/.env >/dev/null && sudo chmod 600 /opt/dreamjob/.env" < .env
```

Puis ajoute les deux lignes propres au serveur :

```bash
ssh -t ubuntu@dreamjob sudo nano /opt/dreamjob/.env
```

```
DREAMJOB_URL=https://dreamjob.TON-RESEAU.ts.net
NTFY_SUJET=une-suite-longue-et-imprevisible-de-mots
```

`TON-RESEAU` : le nom de ton réseau, visible dans la console Tailscale (DNS).
`NTFY_SUJET` : invente-le long, il sert de mot de passe aux notifications.

## 7. Déployer — 10 min la première fois

Depuis ton PC, à la racine du projet :

```bash
deploiement/deployer.sh dreamjob --donnees
```

Cela envoie le code, ta base (offres, profil, candidatures), ton modèle de CV et
tes dossiers de candidature, puis construit et démarre l'application.

`--donnees` ne sert **qu'une fois**. Relancé plus tard, il refuse : la base du
serveur porte alors les comptes de tes amis et tes candidatures récentes, que
celle du PC n'a pas. Pour la remplacer malgré tout, `--donnees --ecraser` — elle
est d'abord mise de côté dans `data/avant-ecrasement-<date>/`.

## 8. Ton compte (toi) — 1 min

```bash
ssh -t ubuntu@dreamjob "cd /opt/dreamjob && sudo docker compose exec dreamjob python -m app.compte creer ton@email.fr"
```

Tu saisis le mot de passe au clavier (12 caractères minimum) : il n'apparaît
nulle part.

Ce premier compte est **le tien** : il reprend tout ce que l'étape 7 a envoyé
(profil, recherches, offres notées, candidatures). Crée-le avant ceux de tes
amis.

## 9. Ouvrir l'accès HTTPS — 1 min

```bash
ssh ubuntu@dreamjob sudo tailscale serve --bg 8000
```

DreamJob est maintenant sur **https://dreamjob.TON-RESEAU.ts.net**, depuis ton PC
comme depuis ton téléphone — et nulle part ailleurs.

**Désactive l'expiration de la clé du serveur.** Tailscale demande par défaut de
reconnecter chaque machine tous les 180 jours : au bout de six mois, le serveur
continuerait de tourner — veille, résumé du matin — mais tu ne pourrais plus
ouvrir l'interface. Dans la console Tailscale (login.tailscale.com), onglet
*Machines*, menu « … » de **dreamjob** → *Disable key expiry*.

## 10. Les notifications sur ton téléphone (toi) — 2 min

Installe l'application **ntfy** et abonne-toi au sujet choisi à l'étape 6.

Tu recevras deux sortes de messages :

- **une alerte par offre verte, dans la demi-heure où elle paraît** (la
  « veille », de 7 h à 22 h). Un clic ouvre directement sa fiche. Au-dessus de
  90, elle sonne même en mode discret. Quinze alertes par jour au plus ;
- **le résumé du matin**, après le scan quotidien : les vertes de la nuit, et
  celles de la veille au-delà du plafond. Une offre déjà signalée n'y revient
  jamais.

**Un même poste ne sonne qu'une fois.** Publié par la banque puis repris par
France Travail ou Adzuna, ouvert dans dix agences, republié la semaine
suivante : une seule alerte (elle dit « et 9 autres lieux »), et le résumé du
matin ne le répète pas. Deux postes vraiment différents — un autre niveau, un
stage au lieu d'un CDI, un autre pays — sonnent chacun.

Rien de vert, rien d'envoyé. Pour régler l'horaire, la fréquence ou le seuil :
section `veille` de `config.yaml`, puis redéployer.

**La première recherche est longue** : une dizaine de minutes, le temps de lire
les ~160 sites d'employeurs et d'ouvrir leurs offres. Ensuite, chaque passage
n'ouvre que les nouveautés. Le bouton « Lancer une recherche » rend la main
tout de suite ; l'écran se met à jour quand elle se termine.

---

## Ajouter un ami

Chacun a son propre compte : son profil, ses recherches, ses notes, ses
candidatures, ses documents. Il ne voit rien des tiens, et tu ne vois rien des
siens. Les offres trouvées pour vous deux ne sont téléchargées qu'une fois.

1. **L'accès réseau (toi).** Console Tailscale → **Machines** → `dreamjob` →
   **Share** : ton ami accepte avec son propre compte Tailscale (gratuit) et ne
   voit que cette machine, pas le reste de ton réseau.
2. **Son compte (toi, avec lui à côté pour taper son mot de passe)** :

   ```bash
   ssh -t ubuntu@dreamjob "cd /opt/dreamjob && sudo docker compose exec dreamjob python -m app.compte creer ami@email.fr"
   ```

3. **Lui** : il se connecte, remplit son **Profil** (ou importe son CV), crée
   ses **recherches**, et peut saisir son propre sujet ntfy dans son profil.

**Ce que ça te coûte.** Ses lettres et ses CV ciblés passent par ta clé
Anthropic. Chaque compte ami a donc un budget : **2 $ par mois** par défaut
(environ vingt-cinq dossiers), au-delà la génération est refusée jusqu'au 1er du
mois. Pour le changer, ou voir qui a dépensé quoi :

```bash
ssh -t ubuntu@dreamjob "cd /opt/dreamjob && sudo docker compose exec dreamjob python -m app.compte budget ami@email.fr 5"
```

```bash
ssh -t ubuntu@dreamjob "cd /opt/dreamjob && sudo docker compose exec dreamjob python -m app.compte lister"
```

`aucun` à la place du montant retire la limite.

**DogFinance reste à toi seul** : ses conditions n'autorisent qu'un usage
personnel. Les recherches de tes amis interrogent France Travail, Civiweb,
Adzuna et les sites des employeurs, jamais DogFinance.

---

## Ensuite

| Pour… | Commande (Git Bash, racine du projet) |
|---|---|
| Mettre à jour le code | `deploiement/deployer.sh dreamjob` |
| Voir les journaux | `ssh ubuntu@dreamjob "cd /opt/dreamjob && sudo docker compose logs --tail 100"` |
| Changer ton mot de passe | `ssh -t ubuntu@dreamjob "cd /opt/dreamjob && sudo docker compose exec dreamjob python -m app.compte mot-de-passe ton@email.fr"` |
| Ajouter un ami | voir « Ajouter un ami » ci-dessus |
| Voir les comptes et leurs dépenses | `ssh -t ubuntu@dreamjob "cd /opt/dreamjob && sudo docker compose exec dreamjob python -m app.compte lister"` |
| Rapatrier la dernière sauvegarde | `scp "ubuntu@dreamjob:/opt/dreamjob/data/sauvegardes/dreamjob-*.db" .` |

**Ce qui s'entretient tout seul.** Chaque nuit à 3 h 30, une copie de la base
(les sept dernières sont gardées, dans `data/sauvegardes`) et le ménage du cache
des pages lues. Les journaux de Docker sont plafonnés à 50 Mo. Une recherche
interrompue par un redéploiement est close au redémarrage. La veille lit
environ 1 Go par jour sur les sites des employeurs ; le trafic est illimité
chez OVH : ce n'est pas un poste de dépense. Les sauvegardes de DreamJob
restant sur le même disque, la **sauvegarde automatique d'OVH** (incluse,
quotidienne) protège contre la perte du serveur lui-même — elle ne garde qu'un
jour : rapatrie de temps en temps une copie sur ton PC (tableau ci-dessus).

**Les mises à jour de sécurité** s'installent seules, sans redémarrer le
serveur. Un redémarrage de temps en temps (`ssh ubuntu@dreamjob sudo reboot`)
les applique toutes ; DreamJob, Docker et Tailscale repartent d'eux-mêmes.

**Ta machine locale** continue de fonctionner comme avant, avec sa propre base.
Une fois le serveur en place, c'est lui qui fait foi : évite de postuler depuis
les deux, les candidatures ne se synchronisent pas.
