# DreamJob

Application **locale** de recherche d'emploi : agréger les offres → les scorer →
générer CV et lettre → postuler → tracer les candidatures pour France Travail.

Un compte par personne : le propriétaire et deux ou trois amis. Tourne en local
(un seul compte, sans connexion), ou hébergé sur un VPS joignable uniquement par
Tailscale (`deploiement/GUIDE.md`). Rien ne sort sauf les appels à l'API
Anthropic, aux sources d'offres et, hébergé, la notification du matin.

---

## Commandes

| Objectif | Commande |
|---|---|
| **Installer** (une seule fois) | `.\setup.cmd` |
| **Raccourci de bureau** (une seule fois) | `.\creer-raccourci.cmd` |
| **Lancer** (API + interface) | double-clic sur *DreamJob*, ou `.\dev.cmd` |
| Tests backend | `cd backend; .\.venv\Scripts\python.exe -m pytest` |
| Typage frontend | `cd frontend; npx tsc -b` |
| Compiler l'interface | `cd frontend; npm run build` |
| Déployer (après un commit) | `deploiement/deployer.sh dreamjob` — voir `deploiement/GUIDE.md` |
| Nouvelle migration | `cd backend; .\.venv\Scripts\alembic.exe revision --autogenerate -m "message"` |
| Appliquer les migrations | `cd backend; .\.venv\Scripts\alembic.exe upgrade head` |
| Mesurer le score | `backend\.venv\Scripts\python.exe outils\evaluer_score.py --detail` |

Interface : http://localhost:5173 — API : http://127.0.0.1:8000/docs

**Pourquoi `.cmd` et non `.ps1`.** Windows bloque par défaut l'exécution des
scripts PowerShell (`ExecutionPolicy`). Les `.cmd` échappent à cette
restriction : ils appellent le `.ps1` avec un contournement valable pour ce seul
processus. Aucun réglage de sécurité de la machine n'est modifié — et il ne faut
pas en modifier : c'est une protection légitime.

**Le raccourci de bureau.** `creer-raccourci.cmd` pose un *DreamJob.lnk* sur le
Bureau, avec une icône générée en Python pur (`outils/icone.py` — pas de Pillow
à installer pour dessiner quatre disques). Il vise `powershell.exe` et non
`dev.cmd`, ce qui permet `-WindowStyle Hidden` : la console du lanceur reste
invisible, seules les deux fenêtres des serveurs s'affichent — elles portent les
logs, et les fermer arrête l'application. Le Bureau est résolu par
`[Environment]::GetFolderPath` : `$env:USERPROFILE\Desktop` se trompe quand il
est redirigé vers OneDrive.

**`dev.ps1` fait quatre choses qu'un double-clic exige** et qu'une ligne de
commande pardonnait :

- **Il applique les migrations avant l'API**, comme l'image Docker. Il ne le
  faisait pas : `create_all` crée les tables manquantes mais n'ajoute jamais une
  colonne, et la première mise à jour qui en apportait une aurait fait planter
  l'API à sa première requête.
- **Il relève Ollama.** Le moteur des lettres démarre avec la session, mais il
  lui arrive de tomber : l'application se lançait alors en mode dégradé sans
  que rien ne le signale, jusqu'à ce qu'une lettre échoue.
- **Il ne relance pas ce qui tourne.** Un second double-clic démarrait un Vite
  de plus, qui se rabattait sur le port 5174 — deux interfaces, dont une que
  personne ne regarde.
- **Il attend que le port réponde** au lieu de dormir cinq secondes. À froid,
  Vite met plus longtemps et le navigateur s'ouvrait sur une page morte.

**Sonder un port se fait avec `Get-NetTCPConnection`, jamais avec `TcpClient`.**
Vite n'écoute que sur `::1` quand l'API écoute sur `127.0.0.1` ; or PowerShell 5.1
s'appuie sur .NET Framework, où `New-Object TcpClient` crée une socket **IPv4
seule** — elle ne peut pas joindre `::1`, quelle que soit la façon d'écrire
l'adresse. La sonde déclarait l'interface morte alors qu'elle répondait.

`make` fonctionne aussi (`make dev`, `make test`) si GnuWin32 est dans le PATH.

**`npx tsc --noEmit` ne vérifie RIEN.** Le `tsconfig.json` racine a
`"files": []` et ne fait que référencer les deux autres : sans `-b`, tsc n'a
aucun fichier à contrôler et répond OK. C'était la commande documentée ici ;
tous les « typage OK » annoncés avec elle étaient vides. La première vraie
compilation (`npm run build`, qui lance `tsc -b`) a trouvé trois erreurs, dont
une propriété de paramètre refusée par `erasableSyntaxOnly` — l'interface
n'avait jamais été compilée pour la production.

---

## Arborescence

```
DreamJob/
├─ config.yaml          réglages : poids du scoring, sources actives, chemins
├─ employeurs.yaml      les sites carrières suivis, leur logiciel, leur statut
├─ .env                 secrets uniquement (jamais versionné)
├─ setup.cmd / dev.cmd  installation / lancement (appellent les .ps1)
├─ creer-raccourci.cmd  pose le raccourci DreamJob sur le Bureau
├─ outils/              icone.py (genere dreamjob.ico) · creer-raccourci.ps1
├─ templates/           cv_modele.docx — le modèle Word personnel
├─ data/                base SQLite, caches, logs (jamais versionné)
│
├─ backend/
│  ├─ migrations/       Alembic
│  ├─ tests/            pytest
│  └─ app/
│     ├─ main.py        application FastAPI
│     ├─ config.py      config.yaml + .env
│     ├─ db.py          moteur SQLite
│     ├─ models/        tables SQLModel
│     ├─ api/           routeurs HTTP
│     ├─ connectors/    base · http (débit, cache) · registry · une source = un fichier · employeurs/ (un logiciel = un fichier)
│     ├─ services/      dedup · scan · veille · scoring · acces (comptes) · budget · notification
│     ├─ scoring/       lexique · exigences · extraction · cible · corpus · score · explain — pur code
│     ├─ documents/     docx_outils · intitule · cv_render · ciblage · correspondance · lettre · controles · exemples · pdf · dossier
│     ├─ importers/     CV .docx/.pdf → profil structuré
│     ├─ exports/       export Excel pour France Travail
│     └─ llm/           client Anthropic + cache
│
└─ frontend/src/
   ├─ api/              client HTTP, types, hooks TanStack Query
   ├─ components/       éléments réutilisables
   ├─ pages/            Offres · OffreDetail · Candidatures · Profil
   └─ lib/format.ts     dates FR, ancienneté, couleur de score
```

---

## Identité visuelle

Les jetons vivent dans `frontend/src/index.css`, dans un bloc `@theme` — jamais
en dur dans les composants. La palette reprend celle de l'icône du raccourci
(`outils/icone.py`) : le bureau et l'application parlent la même langue.

| Jeton | Rôle |
|---|---|
| `encre` | la structure : en-tête sombre, titres, texte |
| `ambre` | **l'action, et rien d'autre** : postuler, générer, filtrer |
| `craie` | les fonds — un blanc cassé chaud, pas un gris bleuté |
| `verdict` | la lecture d'un score : fort, moyen, faible |
| `succes` / `alerte` | états de réussite et d'avertissement |

**L'ambre ne désigne que ce qui se clique.** Un avertissement en ambre se
confondrait avec un bouton, d'où la famille `alerte`, franchement jaune. Le vert
de Tailwind jurait avec une palette chaude : `succes` reprend le vert profond du
verdict.

**Les gris sont chauds.** `craie` plutôt que `slate` : sur un écran qu'on fixe
des heures, le gris bleuté fatigue. C'est le seul motif du remplacement des 158
classes `slate-` d'origine.

**Le score est un anneau, pas une pastille.** Une pastille ne donne qu'un
chiffre ; l'anneau montre la proportion, donc se lit sans être lu. Il reprend la
figure du viseur de la marque (`components/Marque.tsx`), qui est aussi celle de
l'icône. Sur la fiche détail, le verdict est doublé **en toutes lettres** :
« 91 » ne se lit qu'en connaissant les seuils, « correspond bien » se lit seul.

**Les listes de chips se replient au-delà de dix** (`Chips.tsx`). Vingt-cinq
pays alignés forment un mur qu'on ne parcourt pas. Les options actives sont
remontées en tête : replié, on doit voir ce qu'on filtre.

**La police est auto-hébergée.** IBM Plex Sans, en variable, servie depuis
`node_modules` via npm — jamais depuis Google Fonts, qui enverrait une requête à
chaque ouverture alors que le projet ne sort pas de la machine. Seuls le latin et
le latin étendu sont déclarés : le paquet fournit aussi le grec, le cyrillique et
le vietnamien, que `unicode-range` empêche de télécharger mais que le build
copiait quand même. 76 Ko au total.

**Mode sombre : on ne redéfinit que les valeurs des jetons.** Pas une seule
classe conditionnelle dans les composants — c'est tout l'intérêt d'avoir posé des
jetons sémantiques. Deux précautions ont été nécessaires :

- les **27 `bg-white`** codés en dur devaient d'abord devenir `bg-surface`, sans
  quoi les cartes seraient restées blanches ;
- l'en-tête utilisait `bg-encre-950`, or l'encre sert de couleur de **texte**
  partout ailleurs et s'inverse : la barre serait devenue blanche. D'où
  `--color-barre`, qui reste sombre dans les deux thèmes — et le voile de
  l'onglet actif reste `bg-white/10`, pas `bg-surface`.

Le thème a **trois** états, pas deux : « système » suit Windows et reste le
défaut. Un script en tête d'`index.html` applique le choix avant tout rendu,
sinon la page apparaît en clair une fraction de seconde avant de basculer.

Contrastes mesurés sur les deux thèmes : de 5,3 à 15,2 pour un seuil AA à 4,5.

---

## Conventions

**Langue.** Interface, messages d'erreur, noms de champs en base et
identifiants de code : **en français**. Les mots-clés techniques restent en
anglais (`Offer`, `hash`, `score`).

**Concurrence SQLite.** Le planificateur écrit depuis son propre thread pendant
que l'API sert des requêtes ; en WAL, SQLite n'autorise qu'un écrivain. Sans
attente explicite (`timeout` + `PRAGMA busy_timeout`, 30 s), la seconde écriture
échoue aussitôt en « database is locked » et l'utilisateur reçoit une 500 pour
un simple conflit passager.

**Durabilité SQLite.** `synchronous=FULL` (et non NORMAL) : en WAL + NORMAL,
une transaction validée peut encore se perdre à l'arrêt brutal de la machine. Le
volume d'écriture est minuscule, la sécurité ne coûte rien. L'API fait en plus un
`wal_checkpoint(TRUNCATE)` à l'arrêt, pour que les données récentes ne restent
pas dans le seul fichier annexe `dreamjob.db-wal`.

**Dates.** En base : UTC *naïf* (SQLite ne stocke pas le fuseau) via
`models/base.py:maintenant()`. L'API renvoie de l'ISO ; le front interprète en
UTC puis affiche en heure locale (`lib/format.ts`). Aucune date locale n'entre
en base.

**JSON en base.** Les blocs riches du profil (compétences, expériences…), le
détail du score et la charge utile brute des offres sont des colonnes JSON.
Édités d'un bloc, sans vie propre : pas de tables satellites.

**Pays.** `models/enums.py:PAYS_PAR_ZONE` — 42 pays groupés en quatre zones, orientés
places financières et pays francophones. `PAYS_FILTRES` en est la mise à plat.
L'écran Profil affiche les groupes (quarante chips à plat sont illisibles),
l'écran Offres garde une liste à plat puisque les compteurs de facettes n'y
montrent que les pays réellement présents.

**Contrats et statuts.** Stockés en texte simple, pas en type ENUM SQL :
ajouter un statut ne demande aucune migration. Les valeurs de référence sont
dans `models/enums.py`, la validation se fait dans la couche API.

**Migrations.** Alembic fait foi. `create_all()` au démarrage n'est qu'un filet
de sécurité. `migrations/script.py.mako` importe `sqlmodel` — nécessaire, les
autogénérations produisent des `sqlmodel.sql.sqltypes.AutoString`. **Une colonne
`NOT NULL` ajoutée à une table existante exige un `server_default`** : l'autogénération
l'omet systématiquement, et SQLite refuse alors la migration. Arrivé trois fois.

**Tests : jamais la vraie base, jamais une date figée face à l'horloge.** Un test
du planificateur lisait `app.db.engine`, donc la base de l'utilisateur : il
passait parce que le dernier scan réel était récent, pas parce que la base était
vierge, et il est tombé vingt-cinq jours plus tard. Trois tests de fraîcheur
dataient leurs offres du 30 août quand `calculer` mesure par rapport à
aujourd'hui : même effet, même délai. Un module qui lit l'horloge se teste avec
des dates relatives à `maintenant()`, et tout test qui passe par `engine`
redirige celui-ci vers la base temporaire (`monkeypatch.setattr(module, "engine", …)`).

**Écrire du code depuis un script shell.** Un `\b` dans une chaîne Python non
brute devient un octet BACKSPACE, un `\n` passé par `sed` ou un heredoc devient
un vrai saut de ligne au milieu d'une chaîne. Les deux sont arrivés ici, le
premier sans aucune erreur visible. Pour du code, l'outil d'édition — et
`grep -c $'\x08'` après coup.

---

## Les trois règles à ne pas casser

**1. Le score n'appelle JAMAIS de LLM.**
Scorer, ce n'est pas *extraire* : c'est comparer une offre à un profil déjà
connu. Les huit critères se calculent en pur code — le métier et le contenu
par comparaison lexicale pondérée (synonymes, expressions, rareté des mots), le
niveau, le diplôme et les certifications lus dans le texte par des motifs, le
lieu et le contrat déjà structurés, la langue par détection statistique.
Déterministe, rejouable, gratuit.
Un test (`test_aucun_appel_reseau_pendant_un_scoring`) casse si quelqu'un
réintroduit un appel réseau ici.

**2. Un scan ne rappelle jamais le LLM pour rien.**
Toute extraction est mise en cache dans `llm_cache`, clé = `hash` de l'offre +
type d'appel + modèle. Deux scans identiques ⇒ `ScanRun.nb_appels_llm == 0` au
second.

**3. Le LLM n'invente rien.**
Aucune expérience, aucun diplôme, aucune compétence absente du profil ne doit
apparaître dans une lettre. La contrainte est dans le prompt système **et**
vérifiée par un test.

---

## Modèles LLM

Un modèle par document — réglés dans `config.yaml` :

| Réglage | Modèle | Appelé | Pourquoi |
|---|---|---|---|
| `modele_extraction` | *(inutilisé)* | jamais | le scoring est en pur code |
| `modele_redaction` | `claude-opus-5` | import de CV | rare, structure tout le profil |
| `modele_lettre` | `claude-opus-5-5` | une lettre par candidature | lue en entier par le recruteur : le meilleur modèle s'y paie |
| `modele_ciblage` | `claude-sonnet-5` | un CV ciblé par candidature | reformulation encadrée par des contrôles en pur code |

`llm.fournisseur` choisit entre `anthropic` (payant, par défaut depuis la phase 2)
et `ollama` (local, gratuit). **`ClientLlm._appeler_fournisseur` est le seul endroit où ce choix
se fait** : cache, validation Pydantic et messages d'erreur sont communs. Avant
cet aiguillage, l'import de CV était resté câblé sur Anthropic alors que la
lettre savait déjà tourner en local.

**L'import de CV se fait en quatre passes** (identité, expériences, formations,
compétences). Un modèle local de 7 milliards de paramètres ne tient pas quatorze
champs en un seul appel : il range le nom dans le titre visé et rend zéro
compétence. Découpé, il devient exploitable. Chaque passe a sa propre entrée de
cache (`variante`) : une passe qui échoue ne fait pas perdre les autres.

**Mesuré sur deux dossiers réels** (offre « Analyste Risques Financiers ») :
la lettre en effort `medium` a écrit 5 361 jetons — la réflexion, pour une
lettre d'environ 450 — soit 0,125 $ ; en `low`, 2 209 jetons, 0,062 $, pour une
lettre comparable. `low` est donc le défaut. Le ciblage coûte 0,013 $ par tour.
Un dossier revient à **environ 0,08 $**.

**Ce que coûte un dossier est écrit dans le dossier.** Chaque appel relève ses
jetons et les chiffre (`llm.tarifs`, dollars par million) : `generation.json`
porte `consommation` appel par appel et `cout_usd` au total. L'utilisateur paie
ses générations ; il doit pouvoir le lire sans ouvrir la console Anthropic. Un
modèle sans tarif connu coûte zéro dans le relevé — mieux vaut un coût manquant
qu'un coût inventé.

**Opus 5.5 réfléchit toujours, et ça se paie en jetons de sortie.** Ni
`temperature` (refusé en 400) ni `thinking` (impossible à désactiver) ne sont
envoyés : l'effort (`effort_lettre`, `effort_ciblage`) est le seul réglage de
profondeur. La réflexion compte dans `max_tokens` — à 2 000, la lettre aurait
été tronquée ; le budget est donc de 16 000, en flux. Une réponse terminée par
`max_tokens` ou `refusal` lève une erreur au lieu de livrer un texte coupé, et
seuls les blocs `text` sont gardés : la réflexion n'entre jamais dans la lettre.

**La clé se vérifie sans être lue.** `models.list()` confirme l'authentification
sans rien consommer. Deux clés collées de travers ont été repérées ainsi — des
caractères parasites avant `sk-ant-` — sans jamais afficher la valeur : un
secret qui passe dans une conversation doit être renouvelé.

**Le local reste possible, et gratuit** : `llm.fournisseur: ollama`
(`mistral:7b`, RTX 3060 **Laptop 6 Go**). Le CV n'est alors pas ciblé — une
reformulation qui ne doit rien ajouter est précisément ce qu'un modèle de 7
milliards de paramètres fait mal.

**Le modèle ne tient pas entièrement dans la carte, et tout en découle.**
mistral:7b réclame ~5,1 Go quand la carte n'offre que 4,6 Go libres : Ollama
place **28 couches sur 33** sur le GPU, les 5 autres sur le processeur. Débit
mesuré : **25 jetons/s**, pas les ~100 longtemps annoncés ici. Pire, quand une
autre application réclame de la mémoire vidéo, Windows migre silencieusement
celle d'Ollama vers la RAM au lieu d'échouer : le débit s'effondre **d'un
facteur cent, par à-coups**. Constaté sur une génération réelle — six blocs de
512 jetons ont mis 15, 76, 43, 60, 74 puis 3 secondes pour un travail identique.
Anthropic reste branchable pour qui veut une meilleure qualité de lettre.
Attention : un modèle local invente plus facilement — le garde-fou
anti-invention doit **rejeter et régénérer**, pas seulement avertir.

Une clé « liée à une identité » exige en plus `ANTHROPIC_WORKSPACE_ID` dans
`.env` — sans lui, l'API répond `400 anthropic-workspace-id is required`.
C'est le cas de la clé utilisée ici.

Un compte sans crédits répond `400 Your credit balance is too low` : la clé est
valide, l'authentification passe, seul l'appel échoue. Ces deux pannes sont
traduites en français dans `app/llm/client.py` et couvertes par des tests.

**Le client Ollama travaille en flux, et surveille le silence.** Un mur
d'horloge est le mauvais outil : la limite de 300 s a coupé une génération après
271 s de traitement de prompt, alors qu'il restait une trentaine de secondes —
271 secondes de calcul jetées et **aucune lettre**. `httpx` applique son délai
`read` à chaque fragment, ce qui donne exactement la sémantique voulue : un
modèle lent mais vivant va au bout, un modèle bloqué échoue. `DELAI_TOTAL` reste
en garde-fou contre un flux qui goutte indéfiniment.

**Le message d'erreur nomme la cause, pas le symptôme.** « Ollama a échoué :
timed out » n'apprend rien. `_diagnostic_lenteur` dit ce qui se passe — la carte
graphique est saturée — et ce qu'on peut y faire.

**`keep_alive` est envoyé à chaque appel.** Sans lui, Ollama décharge le modèle
après cinq minutes ; entre la génération du CV (LibreOffice, une trentaine de
secondes) et celle de la lettre, il avait le temps de partir, et chaque document
rechargeait 4,4 Go depuis le disque.

**Les reproches à la lettre vont à la FIN du message, jamais dans le prompt
système.** Le cache de llama.cpp est un cache de **préfixe** : toucher au début
de la conversation l'invalide, et les 3 088 jetons du prompt étaient retraités
de zéro à chaque tentative — trois tentatives, trois fois le coût complet. Après
correction, mesuré sur l'offre qui échouait : essai 1 à 2,5 s de prompt, essais
2 et 3 à **0,4 s**. Lettre produite en 65 s au lieu d'un échec à 300 s. Un test
(`test_le_prompt_systeme_ne_bouge_pas_d_une_tentative_a_l_autre`) verrouille
l'invariant. Bénéfice secondaire : un petit modèle obéit mieux à ce qu'il vient
de lire qu'à une consigne enfouie dans 767 jetons de prompt système.

Les erreurs de l'API remontent **telles quelles** à l'utilisateur
(`app/llm/client.py`) : reformuler la cause fait perdre du temps au diagnostic.

---

## Le score en détail

**Le score mesure à quel point une offre correspond au CV — à tout le CV.** Il a
été refait en version 7, et **mesuré** : 182 offres réelles de la base,
étiquetées à la main de 0 (hors sujet) à 3 (cœur de cible), servent de
référence (`outils/etiquettes_score.py`). `outils/evaluer_score.py` rejoue le
score sur la base, en lecture seule, et compare son classement aux étiquettes.
**Un réglage du score se mesure, il ne se devine pas.**

| Mesure | v6 | v7 |
|---|---|---|
| Offres pertinentes (étiquette ≥ 2) dans le top 20 | 6 | **20** |
| Offres hors sujet dans le top 20 | 2 | **0** |
| NDCG@50 — qualité du haut du classement | 0,37 | **0,89** |
| Concordance — paires d'offres dans le bon ordre (0,5 = hasard) | 0,62 | **0,84** |
| Note moyenne, étiquettes 3 / 2 / 1 / 0 | 58 / 56 / **63** / 42 | **70 / 54 / 37 / 21** |

En v6, les postes « à la marge » (comptable, RAF) avaient une meilleure note
moyenne que le cœur de cible : le mot « financier » suffisait à donner 100 sur
le secteur, et le top 20 était plein de « Responsable administratif et
financier », dont un DAF pour trois ans d'expérience.

### Trois étages, et une seule question fait le score

`note = pertinence × facteur(accessibilité) × facteur(conditions)`

| Étage | Critères | Rôle |
|---|---|---|
| **Pertinence** | métier 65, contenu 35 | le poste est-il celui du candidat ? **C'est elle qui fait le score** |
| **Accessibilité** | niveau 50, diplôme 20, langue 30 | peut-il l'obtenir ? **Ne fait que retirer**, jusqu'à 60 % (`part_accessibilite`) |
| **Conditions** | lieu 45, contrat 35, fraîcheur 20 | le veut-il, ici et maintenant ? **Module**, jusqu'à 30 % (`part_conditions`) |

Chaque groupe est normalisé à part. **Quand niveau, diplôme et langue
s'additionnaient au reste, un poste sans rapport mais « compatible » empochait
d'office le tiers du score** : les faire multiplier a fait passer la
concordance de 0,79 à 0,83 d'un coup.

**Les points rédhibitoires plafonnent à 15**, quoi qu'il arrive ailleurs : une
langue exigée que le candidat ne parle pas, un poste hors de portée en
expérience (direction, ou six ans d'écart), un contrat ou un pays refusés, une
certification exigée qu'il n'a pas (expert-comptable, DSCG, CFA…), un poste
réservé aux fonctionnaires titulaires. Ils ouvrent l'explication.

### Ce que le score lit du CV (`scoring/cible.py`)

**Tout le CV, pas six phrases.** La v6 ne regardait que la liste de compétences
et les secteurs ; les expériences, les missions, les diplômes et les recherches
enregistrées étaient ignorés. Il en est tiré :

- **les intitulés visés**, pondérés : titre visé et recherches (1,0 — ce que le
  candidat dit chercher), postes occupés (0,9 pour le plus récent, puis
  dégressif), diplômes et secteurs (0,6), **mots-clés de chaque expérience**
  (0,6 × récence). Sans ces derniers, un CV de risque de crédit ne reconnaissait
  pas « Analyste crédit » : aucune recherche ne disait « crédit » ;
- **un vocabulaire pondéré** : chaque terme selon l'endroit où il apparaît —
  une compétence ancrée pèse 1,0, un mot d'une mission ancienne 0,4. Les mots
  creux (« connaissance », « maîtrise », « pack ») n'y entrent pas ;
- **le vocabulaire des domaines visés** (`DOMAINES`), à 0,35 : un junior qui vise
  le middle office n'a pas encore écrit « règlement-livraison ». **Ces mots ne
  servent qu'à classer — ils n'entrent jamais dans un document**, où ils
  seraient des mensonges.

### Le vocabulaire commun (`scoring/lexique.py`)

Tout passe par `jetons` : mots vides retirés, chaque mot ramené à sa **forme
canonique** — sa famille de synonymes, sinon sa racine (pluriel, féminin,
« directrice » → « directeur », « administrative » → « administratif »).
**Les expressions comptent** : les paires de mots voisins, sans ordre —
« risque de crédit » et « credit risk » donnent la même ; « middle office »
n'est pas « office manager ».

Retirés d'un intitulé, parce que jugés ailleurs : contrat, niveau, genre, lieu,
restes d'écriture inclusive (« administratif(ve) »), et **les mots de diplôme**
— le « Master » d'un Master 2 rapprochait le CV d'un poste de « Scrum Master ».

Deux familles de synonymes étaient fausses et ont été séparées :
**« négociation » n'est pas « trading »** (un CV qui négocie des partenariats
devenait un CV de trader) et **« manager » n'est pas « gestion »** (c'est un
niveau, rangé avec « responsable »).

### Pertinence 1 — le métier

L'intitulé de l'offre face aux intitulés visés, dans les deux sens :

- **rappel** : l'offre reprend-elle un intitulé visé ? Le meilleur, pondéré, plus
  un peu du second. Un intitulé visé d'un seul mot banal (« Finance », une
  recherche V.I.E) ne peut pas à lui seul faire une cible : sa **spécificité**
  se mesure à la rareté de ses mots dans les annonces ;
- **précision** : le candidat parle-t-il le vocabulaire de l'intitulé ?

Combinés par **moyenne harmonique** : les deux sont nécessaires. Reprendre
« analyste risques » ne suffit pas si le reste dit « cybersécurité » ;
connaître tous les mots ne suffit pas si ce n'est aucun des postes cherchés.
Mesurée contre les étiquettes, elle devance toute moyenne pondérée.

Deux défauts corrigés en route, mesurés : **une expression n'entre dans la
précision que reconnue** — « Trading Risk and Control » était pénalisé parce
que le CV ne dit pas « risk trading », alors qu'il en connaît chaque mot (+0,05
de concordance) ; et le poids d'un mot de l'intitulé suit la **racine** de sa
rareté, pour qu'un mot rare (« Guardian ») n'écrase pas tout ce que le candidat
reconnaît.

### Pertinence 2 — le contenu

Similarité cosinus entre l'annonce (chaque terme selon sa répétition et sa
rareté, l'intitulé compté double) et le vocabulaire pondéré du CV. **Étalonnée
sur les offres du compte** : celle qui atteint le 95e centile vaut 100
(`score.etalonner`, une fois par scoring). Un CV court donne des similarités
minuscules — le 95e centile réel est à 0,047 — et un plancher fixe à 0,12
écrasait tout le critère.

Une première version extrayait les « termes clés » de l'annonce puis mesurait
leur couverture : sur des annonces courtes, où chaque mot n'apparaît qu'une
fois, « le plus rare » n'est pas « le plus exigé », et la liste se remplissait
de « Sopra », « Steria » et « autonome, méthodique ». Un mot ne compte que s'il
revient dans quelques annonces — seuil qui **suit la taille du corpus**, sans
quoi le fil d'un compte qui démarre serait vide.

### Accessibilité (`scoring/exigences.py`)

- **Niveau** : lu dans l'intitulé (stage, junior, intermédiaire, senior,
  encadrement, direction), confronté aux années du profil ; les années
  chiffrées priment. Les grades bancaires trompent : un « Assistant Vice
  President » a quelques années, un « Vice President » encadre sans diriger.
  « 3 à 5 ans » s'ouvre à 3, et « fort de 30 ans d'expérience » parle de
  l'entreprise. **Un stage n'est pas « trop junior »** si le candidat accepte
  les stages.
- **Diplôme** : Bac+2 pour un Bac+5 vaut 55 — pas fermé, rarement le bon poste.
  **« Maîtrise d'Excel » n'est pas un diplôme** : le mot transformait un poste
  Bac+2 en Bac+4, dans une annonce française sur deux.
- **Certifications et statut** : exigées seulement près d'un « requis »,
  « obligatoire »… — « le CFA est un plus » ne ferme rien. Un poste ouvert
  aussi aux contractuels n'est pas réservé aux fonctionnaires.
- **Langue** : la langue de rédaction ET celles exigées — la plus dure décide.
  Le niveau du profil est saisi en texte libre : plusieurs niveaux reconnus ⇒ le
  plus prudent (« courant (B2) » vaut B2) ; une saisie illisible (« TOEIC 775 »)
  vaut 70, jamais plus.

### Conditions

**Lieu** sur quatre paliers (votre ville 100, votre pays 80, pays accepté 60,
refusé 0) — sans pays de résidence, on ne devine pas et on ne pénalise
personne. **Contrat** selon l'ordre des préférences, de 100 à 60. **Fraîcheur**
linéaire de 7 à 120 jours : le seul départageur continu.

### Les seuils de couleur

Vert à 75, orange à 50 — inchangés, et validés contre les étiquettes : sont
vertes 54 % des offres cœur de cible, 14 % des offres proches, **aucune** offre
à la marge ou hors sujet.

### Tenir les notes à jour

**Le score lit tout le CV et toutes les recherches : chaque changement les
recalcule.** Enregistrer le profil, importer un CV, créer ou modifier une
recherche relance le calcul du compte, après la réponse (`services.scoring.rescorer`) ;
un scan manuel note ses nouvelles offres ; et l'application, à son démarrage,
remet à jour ce qu'une nouvelle version du score a rendu caduc
(`scheduler.rescorer_tout`). Avant, un profil modifié ou un score amélioré
laissaient les anciennes notes à l'écran jusqu'au lendemain. Le recalcul reçoit le moteur de la requête,
**jamais le moteur global** — depuis un test, celui-ci viserait la vraie base.

Le corpus et l'étalonnage portent toujours sur **tout** le fil du compte, même
quand quelques offres seulement sont à noter : une offre se juge par rapport aux
autres. Un score stocké vieillit (fraîcheur, corpus) : ce qui a plus d'un jour
est recalculé. Les 4 486 offres du propriétaire se notent en 15 secondes,
extraction comprise.

**Deux compteurs de version.** `scoring.version` (`config.yaml`) marque un
changement de poids ; `extraction.VERSION` un changement de signaux — lu sur la
note de chaque compte, car le premier qui rescore met à jour les signaux de
l'offre.

**Synonymes métier** (`scoring/synonymes.py`) : les offres de ce domaine sont
massivement bilingues. Les familles qui partagent un mot sont fusionnées
**avant** l'index inversé, sans quoi la relation cesserait d'être symétrique.

**Le cache de `normaliser` ne sert que les chaînes courtes**
(`LONGUEUR_CACHABLE`) : une description entière n'y fait jamais mouche.

**Le vrai plafond reste le profil.** Des compétences en phrases (« Esprit
d'analyse et de synthèse ») ne rencontrent aucune annonce ; des termes courts
(« Risque de crédit ») et des mots-clés d'expérience renseignés, si.

---

## Déduplication

Deux filets, deux problèmes :

- `UniqueConstraint(source, source_id)` — relancer le même scan ne recrée rien.
- `Index unique sur hash` — la même annonce republiée ailleurs est reconnue.
  `hash = sha256(titre + entreprise + lieu + 500 premiers caractères de la
  description, normalisés)`.

---

## Sources d'offres

Toute source implémente `BaseConnector.fetch(query: SearchQuery) -> list[RawOffer]`
et s'active dans `config.yaml`. **Avant d'écrire un connecteur** : vérifier
`robots.txt` et les CGU. Sans API ni flux public autorisé, le connecteur reste
`actif: false` et **la raison exacte est consignée dans `config.yaml`** — c'est
la trace qui justifie chaque décision.

| Source | État | Motif |
|---|---|---|
| France Travail | actif | API officielle v2, validée en réel |
| Civiweb (V.I.E) | actif | `robots.txt` n'interdit que `/refresh`, aucune clause CGU sur l'extraction ; endpoint JSON du site, clé publiée dans sa configuration front |
| Adzuna | actif | API publique documentée, validée en réel. 19 pays, un appel par pays. **Descriptions tronquées à 500 caractères par l'API** : le critère compétences y est structurellement plus faible que sur les autres sources |
| DogFinance | actif | Site spécialisé finance, ~11 000 offres. `robots.txt` autorise `/` et publie trois sitemaps d'offres ; il n'interdit que `/offres?*`, la recherche filtrée — jamais utilisée. Aucune clause CGU sur l'extraction. **Prélèvement plafonné**, voir ci-dessous |
| Sites des employeurs | actif | Les sites carrières de `employeurs.yaml`, par leur logiciel de recrutement — voir « Sites des employeurs » |
| Talent.com | **refusé** | `robots.txt` interdit `/services/api-new/search` et `/search-jobs/*` |
| HelloWork | **refusé** | `robots.txt` interdit `/fr-fr/emploi/recherche.html` et `Disallow: /*?` |
| Welcome to the Jungle | **refusé** | `robots.txt` interdit `*/jobs?query=*` ; API réservée aux partenaires |
| APEC | en attente | `robots.txt` permissif, mais le sitemap ne publie que des pages de recherche et il n'existe pas d'API |

**DogFinance : le plafond est juridique, pas technique.** Le site n'a pas d'API.
Ses sitemaps publient ~11 000 URL et chaque page porte l'offre en JSON
(`__NEXT_DATA__` → `props.initialProps.pageProps.offreSSR`, 36 champs). Mais ses
CGU réservent l'usage des textes « sans le consentement écrit de l'Editeur », et
le droit *sui generis* du producteur de base de données (art. L342-1 CPI)
interdit d'extraire une **partie substantielle** du fonds — indépendamment de ce
que `robots.txt` autorise. D'où la conception :

- on ne rapatrie **jamais** le catalogue : les URL du sitemap sont filtrées
  *localement*, sans rien demander au site ;
- `PLAFOND_PAGES` (40) borne les pages ouvertes **par scan**, toutes recherches
  confondues. Le budget est porté par l'instance du connecteur parce que
  `scan.py` construit une source puis lui passe chaque recherche tour à tour :
  sans cela, quatre recherches enregistrées ouvriraient quatre fois quarante
  pages ;
- la recherche filtrée `/offres?…`, seule chose que `robots.txt` interdise,
  n'est jamais appelée — un test le vérifie.

Ne pas lever ce plafond sans le consentement écrit que les CGU mentionnent.

Deux limites propres à cette source : la localisation manque une fois sur deux
(rattrapée depuis l'intitulé, comme chez France Travail — sinon le critère pays
reste non évaluable), et les sitemaps n'ont pas de `lastmod`, donc aucune
nouveauté n'est repérable sans ouvrir les pages.

Le corps d'une requête peut être un formulaire (`donnees=`, pour OAuth) ou du
JSON (`corps_json=`, pour les API modernes) — Civiweb rejette le premier.

Le client HTTP partagé (`connectors/http.py`) impose 1 req/s **par hôte**, un
User-Agent explicite, un backoff exponentiel (le `Retry-After` du serveur prime)
et un cache disque. Son client `httpx` est créé à la première requête : monter un
contexte SSL coûte ~1 s, inutile quand tout sort du cache.

Un connecteur qui casse n'interrompt jamais les autres. `ScanRun.erreurs`
distingue trois cas, et l'interface doit les traiter différemment :

| `type` | Sens | Ce que l'utilisateur doit faire |
|---|---|---|
| `non_configure` | identifiants absents de `.env` | les renseigner |
| `panne` | la source répond mal | attendre, ou signaler |
| `inattendu` | bug de notre côté | corriger le connecteur |

**Un filtre trop large vaut mieux qu'un filtre trop étroit.** Exemple :
`publieeDepuis` chez France Travail n'accepte que 1/3/7/14/31 jours — on arrondit
vers le **haut**, sinon des offres disparaissent en silence.

---

## Sites des employeurs

**Les offres à la source.** Une banque publie d'abord sur son site ; les
agrégateurs reprennent l'annonce des jours plus tard, parfois jamais, et Adzuna
la coupe à 500 caractères. Avant cette source, la base comptait 12 offres de
BNP Paribas et 10 de Société Générale, qui en ont des centaines d'ouvertes.

**Un connecteur par logiciel, pas par employeur** (`connectors/employeurs/`).
228 employeurs ont été repérés le 2026-09-28 (banques, gestion d'actifs, fonds,
trading, banque privée, assurance, institutions, notation, conseil, cabinets de
recrutement) : leurs sites reposent sur une vingtaine de logiciels, Workday en
tête (32), puis SuccessFactors, Talentsoft, Oracle, Greenhouse. Ajouter un
employeur, c'est une entrée dans `employeurs.yaml` — son statut (`actif`,
`à_venir`, `à_étudier`, `refusé`) et, pour un refus, le motif daté.

**On ne demande pas aux sites de chercher** : un site anglophone ne trouve rien
à « analyste risques ». Chaque employeur est listé une fois par scan, filtré sur
les pays des recherches, du plus récent au plus ancien jusqu'à la fenêtre
(`employeurs.fenetre_jours`, 31 jours pour une recherche sans limite, 1 jour en
veille) ; les intitulés sont comparés ici, avec le vocabulaire du score —
« Risk Analyst » et « analyste risques » donnent les mêmes mots. Au-delà de
deux mots, un peut manquer : « Analyste risques de crédit » trouve « Credit Risk
Officer ».

**Une fiche n'est ouverte que pour une offre nouvelle qui répond.** Le scan
confie au connecteur les identifiants déjà en base (`veut_les_connus`) : une
offre retrouvée est seulement dite « toujours en ligne ». Mesuré sur 29 sites
Workday et les 4 recherches du propriétaire : premier scan 271 offres en
2 min 40, passe de veille en 10 s.

**Le contrat que l'annonce n'écrit pas est un CDI ou un CDD.** Laisser passer un
contrat inconnu versait tous les postes « finance » — 79 conseillers d'agence
de Bank of America — dans la recherche V.I.E. Une recherche réservée aux
contrats particuliers exige qu'ils soient écrits dans l'intitulé. Et le pays de
la fiche a le dernier mot : « 3 Locations » en liste cachait des postes en Inde.

**Mêmes règles que partout, vérifiées à chaque scan.** robots.txt relu selon la
RFC 9309 (`robots.py`) : fichier présent, ses règles ; 4xx, rien n'est
interdit — Oracle renvoie 403 à tout le monde, navigateurs compris ; 5xx ou
injoignable, on s'abstient. `urllib.robotparser` traite 401/403 comme une
interdiction totale : c'est l'ancienne convention, et elle aurait écarté
J.P. Morgan à tort. Un site protégé contre les robots est refusé, **jamais
contourné** : BNP Paribas bloque notre User-Agent (Akamai) sur sa liste, et sa
recherche Avature est désactivée — refusé, motif consigné. Le client HTTP est
devenu sûr entre fils (un verrou par hôte) : les employeurs sont interrogés en
parallèle, jamais deux fois dans la seconde sur un même site.

**Workday** (`workday.py`) : l'interface JSON que la page elle-même appelle,
`POST /wday/cxs/<locataire>/<site>/jobs`. Sans mot-clé, la liste est triée du
plus récent au plus ancien ; le filtre pays accepte plusieurs pays d'un coup ;
la date n'y est que relative (« 30+ Days Ago »), la fiche donne la date exacte
et le pays en code ISO. Le plan du site publié s'arrête à cent offres : la
liste est la seule voie complète. Le total n'est renvoyé qu'avec la première
page.

**Un logiciel par fichier**, chacun documenté en tête avec ce qui a été
vérifié : Workday (29 employeurs), Talentsoft (10 : flux RSS officiel pour la
veille, liste en deux gabarits pour le scan), SuccessFactors (11 : son
robots.txt interdit `/services/`, donc le RSS — on lit la recherche triée par
date), Oracle (8, deux cents offres par page), Greenhouse (6, API publique
officielle), Eightfold (Morgan Stanley, HSBC), Jibe (AXA), Beesite (Deutsche
Bank), le groupe BPCE, et **le plan du site + JobPosting** (`plan_du_site.py`) :
le format que Google exige pour Google for Jobs, lisible quel que soit le
logiciel — Société Générale, BlackRock, Moody's, ING, KPMG, RBC, Fed Finance…
Les microdonnées schema.org en sont le repli. L'intitulé se lit dans le
dernier segment de l'adresse qui porte des lettres : Radancy le range avant
deux numéros (`/job/new-york/risk-analyst/45831/99354208`).

**robots.txt se lit selon la RFC 9309, pas avec `urllib.robotparser`.** Le module
standard applique la première règle rencontrée ; la norme veut la plus précise
(le motif le plus long), l'autorisation l'emportant à égalité. Sur Eightfold
(`Disallow: /` puis `Allow: /api/pcsx`), le module standard interdisait ce que
le site autorise en toutes lettres — et l'erreur inverse laisserait passer une
interdiction. Le groupe retenu est celui qui nomme notre robot **exactement**
(« autre » ne vise pas « AutreRobot »), sinon `*`. `Crawl-delay`, hors norme
mais répandu, est respecté : AXA demande cinq secondes, le client HTTP les
applique à cet hôte (`ClientHttp.ralentir`).

**Pièges rencontrés, un par site :**

- **HSBC** (Eightfold, ancienne interface) choisit, sans lieu précisé, celui de
  l'appelant d'après son adresse IP : un serveur en Allemagne n'y verrait pas
  les offres parisiennes. Il est interrogé pays par pays, en anglais.
- **BPCE** : robots.txt interdit la recherche et les listes ; l'interface qui
  les alimente n'est jamais appelée. Le site publie le plan de ses offres sous
  `/job/`, autorisé : chaque offre est lue comme sa page la lit. L'entité exacte
  (« Caisse d'Epargne Ile de France ») devient l'employeur affiché
  (`Annonce.entreprise`). Le site Oracle vers lequel pointe « Postuler » est
  abandonné (dernière offre en avril).
- **Deutsche Bank** nomme les pays en allemand même dans son interface anglaise,
  et « Unbefristet » (un CDI) était lu CDD : le motif `befristet` prend une
  limite de mot.
- **Un pays hors du vocabulaire doit être nommé pour être écarté.** Inconnu, il
  passait le filtre comme un lieu non précisé : un poste de SCOR à Bucarest
  arrivait dans une recherche limitée à la France. `pays.py` connaît donc aussi
  la Roumanie, les Philippines, Jersey…
- **Une adresse d'offre peut disparaître du site avant son plan** (ING) : la
  fiche en 404 est ignorée et consignée, rien d'autre.

**Refusés, motif daté dans `employeurs.yaml`** : BNP Paribas (liste protégée,
recherche Avature désactivée), Goldman Sachs (robots.txt n'autorise que les
fiches, sans plan du site), Bpifrance et Tikehau (403 à notre User-Agent,
robots.txt compris). Mesuré sur les 79 premiers actifs et les 4 recherches du
propriétaire : 368 offres en 3 min 15, 90 en France ; une passe de veille en
25 s.

---

## Génération des documents

`documents/` produit `~/Jobscout/candidatures/<date>-<entreprise>-<poste>/` avec
`CV.docx/.pdf`, `Lettre_de_motivation.docx/.pdf` et `offre.json` (l'annonce
disparaîtra du site : on en garde une copie).

**Le modèle de CV est la seule source de vérité de l'apparence.** `docx_outils`
ne crée jamais un paragraphe de zéro : il duplique ceux du modèle et remplace
leur texte, donc styles, puces et polices survivent. Les sections sont repérées
par leurs `Heading` ; une rubrique sans contenu est supprimée plutôt que laissée
vide. Deux pièges déjà rencontrés :

- après avoir rempli un bloc, son **dernier paragraphe a changé** (des puces ont
  pu être ajoutées) : le point d'insertion du bloc suivant doit être recalculé,
  sinon les puces migrent d'une expérience à l'autre ;
- les blocs surnuméraires du modèle se suppriment **avant** toute duplication,
  sinon les clones s'intercalent.

Le nom de dossier est borné à 80 caractères : Windows refuse au-delà de 260
caractères de chemin complet.

**Le nettoyage de la lettre ne coupe qu'à la fin.** `nettoyer` retirait tout à
partir de la première formule de politesse rencontrée : « Dans l'attente… »
ouvre couramment un paragraphe de milieu de lettre, et les trois quarts du texte
disparaissaient — la lettre était ensuite rejetée comme trop courte, puis
refusée, alors qu'elle était bonne.

**Un PDF doit être plus récent que sa conversion.** Vérifier son existence ne
suffit pas : si LibreOffice échoue (déjà ouvert, document verrouillé), le PDF de
la génération précédente satisfait le test et part chez le recruteur. On
contrôle le code de retour *et* la date du fichier.

**Le dossier est vidé de ce qu'on y a produit avant chaque régénération.** Sinon
une lettre refusée par le garde-fou laisse en place celle d'avant, décrivant un
profil périmé, à côté d'un CV à jour. Les fichiers déposés par l'utilisateur,
eux, sont conservés.

**Le CV tient sur une page, et c'est mesuré, pas estimé.** Un CV de deux pages
n'est pas une convention discutable : le recruteur lit la première, la seconde
arrive après sa décision. `dossier.py` convertit le CV, compte les `/Type /Page`
du PDF, et rappelle `cv_render.rendre` avec moins de puces par expérience
(`PUCES_PAR_ESSAI`) tant qu'il déborde.

Une première version **estimait** la hauteur en lignes à partir du nombre de
caractères : elle annonçait 55 lignes pour un CV qui en occupait 47, et rabotait
donc les expériences à une seule puce pour un débordement imaginaire. La mise en
page dépend de la police, des marges et des césures du modèle — seul le rendu la
connaît. La première conversion étant de toute façon nécessaire, la mesure ne
coûte rien dans le cas courant. Sans LibreOffice, on ne mesure pas : le CV part
entier, ce qui vaut mieux qu'un CV amputé au hasard.

**Le CV ne porte aucune ligne de mobilité.** Les pays acceptés du profil
servent à filtrer les offres, pas à figurer sur un CV : le recruteur sait où est
son poste, et le candidat qui postule y est par définition disponible. Cette
ligne étalait dix-sept pays sur trois lignes d'en-tête — aucune information, et
assez de place perdue pour faire déborder le document.

**La ligne « Recherche » s'aligne sur le contrat de l'offre.** Un CV envoyé pour
un CDI n'a pas à annoncer qu'on cherche aussi un stage : la liste complète dilue
la candidature et laisse penser qu'on postule à tout. Quand l'offre porte un
contrat que le profil accepte, seul celui-là est mentionné. Contrat non précisé
par la source, ou hors des préférences : on retombe sur la liste — mieux vaut
dire ce qu'on cherche que de taire l'information.

**Le classement du CV parle la même langue que le score.** `_pertinence`
(`cv_render.py`) était une **troisième** implémentation de l'appariement, après
celle des compétences et celle du secteur : simple appartenance d'ensemble, donc
sans synonymes ni pondération des mots génériques. Une expérience « risques de
crédit » ne rencontrait jamais une offre en « credit risk ». Les trois passent
maintenant par `scoring.score.presence` — sans quoi le CV met en avant ce que le
score juge hors sujet, sous les yeux de l'utilisateur.

**Les expériences et les formations suivent les dates, pas la pertinence.** Une
première version triait les expériences par pertinence pour l'offre (l'ordre
changeait sur 231 offres sur 400). Relu sur le CV réel, un stage de mai 2021
passait devant un mandat 2021-2022, et le Master 2020-2025 devant le MBA en
cours : un recruteur français lit un CV de haut en bas en cherchant la dernière
expérience, et un ordre qui n'est pas celui des dates lui fait soupçonner un trou
qu'on cache. La pertinence s'applique désormais **aux puces de chaque
expérience**, pour **choisir** quand le CV déborde — on gardait les N premières
puces du profil, pas celles qui parlent de CETTE offre. Elle ne sert plus à les
**ordonner** : sur le premier dossier réel, « trésorerie augmentée de 100 % »
passait derrière « mise en place du compte de résultat », et « crowdfunding à
150 % de l'objectif » disparaissait. Le recouvrement lexical avec l'annonce ne
voit pas qu'un résultat chiffré vaut plus qu'une tâche : un chiffre compte
désormais comme une pleine correspondance (`BONUS_CHIFFRE`), et les puces
retenues gardent l'ordre choisi par le candidat. Les compétences restent triées
par pertinence.

Le tri **ordonne, il ne sélectionne pas** : retirer une expérience d'un CV y
creuse un trou que le recruteur remarquera. Et il n'injecte aucun mot-clé de
l'annonce — s'attribuer une compétence qu'on n'a pas est une fausse déclaration,
plus grave encore sur un CV que dans une lettre.

**L'intitulé de l'annonce est nettoyé avant d'aller sur le CV**
(`documents/intitule.py`). On le garde — c'est ce que cherche le recruteur dans
son ATS — mais brut, il mettait « (H/F) » sous le nom du candidat dans **45 %**
des offres pertinentes, jusqu'à « Analyste Risques Financiers (H/F)- PARIS
(H/F) ». Sont retirés : marqueurs de genre, contrat, durée, département,
télétravail, références. Le lieu n'est retiré que **s'il est celui de l'offre** :
mesuré, le dernier segment après un tiret est rarement un lieu (« - Bank »,
« - Trading », « - Middle Office »). Seuls les séparateurs **espacés** comptent —
un trait d'union de mot composé (« Front-Office ») n'en est pas un.

**L'objet de la lettre élide** : « candidature au poste de Analyste » était la
première ligne lue par le recruteur dans environ une lettre sur dix. Le corps
rendu par le modèle est élidé aussi (`lettre._elider`) — relevé dans une vraie
lettre : « le poste de « Analyste … » ». Les contrôles anti-invention lisent
indifféremment les deux formes, vérifié avant d'introduire la correction.

**Le genre n'est jamais déduit du prénom.** `Profile.accord` (masculin, féminin,
vide) est saisi par l'utilisateur. Il sert à choisir la moitié d'un intitulé
doublé par France Travail (« Auditeur comptable / Auditrice comptable », 9 % des
offres pertinentes, parfois tronqué en seconde moitié) et à laisser la lettre
écrire « diplômé » au lieu de contourner tout adjectif. Vide, l'intitulé doublé
cède au titre visé et la lettre n'accorde rien.

**Les fichiers portent le nom du candidat** (`CV_Maxime_Nicolas.pdf`), sans
accents : le recruteur recevait cinquante `CV.pdf`. Leurs métadonnées aussi — le
CV partait signé « Un-named » (hérité du modèle), la lettre « python-docx », et
LibreOffice reporte ces champs dans le PDF. Le nettoyage d'un dossier régénéré
efface les anciens noms et ceux que `generation.json` a consignés : sans cela,
l'ancien `CV.pdf` restait à côté du nouveau.

**Le CV n'affiche pas de catégorie de compétences.** Le modèle en propose
(« Quantitatif & données : »), mais les compétences y étaient versées par
tranches sans rapport avec le thème : le rendu portait « Quantitatif & données :
R, VBA, Power BI, Word, PowerPoint ». Un CV ne doit pas affirmer un classement
que son contenu dément.

**L'anti-invention est bloquant, pas indicatif.** `lettre.py` compare chaque nom
propre et chaque année de la lettre au profil et à l'offre ; ce qui est inconnu
déclenche une régénération, en nommant l'erreur au modèle. Après N essais
(`llm.tentatives_anti_invention`), la lettre est refusée : le CV part seul,
l'avertissement est remonté. Mieux vaut pas de lettre qu'une lettre qui ment.

**Cinq contrôles, et deux familles.** `documents/controles.py` les porte tous ;
`lettre.py` ne garde que les prompts et la boucle. La distinction commande le
reste :

| Famille | Contrôle | Ce qu'il attrape | Effet |
|---|---|---|---|
| honnêteté | invention | nom propre ou année inconnus | **bloquant** |
| honnêteté | chiffres | nombre absent du profil et de l'offre | **bloquant** |
| honnêteté | voix | le recruteur s'adresse au candidat | **bloquant** |
| honnêteté | contrat | « alternance » sur une offre en CDI | **bloquant** |
| style | perroquet | 12 jetons recopiés de l'annonce | signalé |
| style | disponibilité | une date que le profil ne donne pas | signalé |
| style | formules creuses | 48 tournures passe-partout | signalé |
| style | ouverture | « C'est avec », « Fort de », « Suite à » | signalé |
| style | rythme | un paragraphe sans phrase de moins de 12 mots | signalé |

Les bloquants rendent la lettre **fausse** : mieux vaut pas de lettre. Les autres
la rendent seulement **convenue** : on livre, on nomme les défauts dans les
avertissements, l'utilisateur retouche en dix secondes. Confondre les deux
faisait refuser des lettres exactes — mesuré, deux offres réelles sur deux sans
le moindre document produit.

**La lettre est en A4, et mesurée.** Le modèle par défaut de python-docx est
au format US Letter (21,6 × 27,9 cm) avec 3,2 cm de marges : la première lettre
d'Opus — 305 mots — envoyait sa seule signature en page 2. Toutes les lettres
l'étaient depuis le début ; celles de mistral, plus courtes, passaient par
chance. Le PDF est désormais compté comme celui du CV, et un débordement est
signalé.

**Le niveau de langue du profil fait partie des sources.** Le contrôle ne lisait
que le nom de la langue : la première lettre d'Opus qui citait « TOEIC 775 »,
tiré du profil, a été rejetée comme une invention, et un second essai payé pour
rien. mistral ne citait jamais ce score — le défaut était resté invisible.

**Les contrôles attrapent les noms, les chiffres et les dates — pas les
affirmations molles.** « Cette responsabilité m'a appris à documenter mes
recommandations » passe : aucun nom, aucun chiffre, et pourtant rien de tel
n'est dans le profil. Une lettre se relit avant l'envoi.

**Les deux côtés doivent tokeniser pareil.** Le vocabulaire autorisé était
découpé par `normaliser().split()`, qui garde le point final, quand la lettre
l'est par `mots()`, qui le retire : le vocabulaire contenait « pte. » et « ltd. »
là où la lettre produisait « pte » et « ltd ». Résultat mesuré sur une offre
réelle de **UQPAY PTE. LTD.** : la lettre refusée trois fois pour avoir cité
l'employeur, et aucun document produit. Toute société en S.A., Inc. ou Co.
tombait dans le même piège.

**Le perroquet n'est pas bloquant, et c'est un choix.** Il ne distingue pas
« j'ai réalisé des travaux de backtesting » — un mensonge — de « je serais amené
à réaliser des travaux de backtesting », qui décrit le poste. Or le prompt
DEMANDE de nommer des éléments de l'annonce : le rendre bloquant revenait à
exiger une chose et à la punir. Son seuil est passé de 8 à 12 jetons pour la
même raison : à 8, « au sein d'un Middle office Assurance H/F en CDI » (10
jetons) était refusé, et le candidat ne pouvait plus nommer le poste visé.

**La voix** est le défaut le plus embarrassant en local : mistral rendait « Je
suis heureuse de vous présenter une opportunité… je recherche un candidat
expérimenté… votre MBA à l'ESLSCA ». Trois causes, toutes dans le prompt : il
disait « pour un candidat » sans jamais dire « **tu es** le candidat » ; « Le
vouvoiement, et rien d'autre » a été compris comme *vouvoyer le candidat* ; et
les consignes parlaient de lui à la troisième personne. « votre équipe » et
« vos besoins » restent permis — c'est la raison d'être du vouvoiement.

**Nommer la faute marche ; demander une relecture, non.** On a d'abord confié au
modèle la critique de son propre brouillon (`PROMPT_RELECTURE`,
`llm.relecture_lettre`) : mistral:7b en conserve la **totalité** des clichés et
n'a changé qu'un mot. Il obéit en revanche très bien quand le reproche est
nommé. D'où la détection en pur code, et ce réglage désactivé par défaut.

**Les reproches sont plafonnés à trois** (`MAX_RAPPELS`). Tout lui reprocher
d'un coup le fait décrocher : au quatrième essai, il rendait la structure du
prompt (« Informations, Formations, Expériences ») au lieu d'une lettre.

**Le few-shot vient des vraies lettres du candidat**, volontairement court pour
la même raison. Les extraits vivent dans le profil (`Profile.exemples_style`,
saisis dans l'écran Profil) ; `documents/exemples.py` n'en garde que le cadre.
Ils ont d'abord été écrits en dur dans le code : avec plusieurs comptes, les
phrases, les chiffres et les employeurs du propriétaire seraient partis dans le
prompt des lettres de tous. Un profil sans extraits n'a pas de bloc d'exemples. Les noms d'entreprises tierces y sont
remplacés par des marqueurs : cités en clair, le modèle les recopiait, et
l'anti-invention les rejetait aussitôt — génération en boucle, sans résultat.

**Le profil est le vrai goulot, pas le modèle.** Aucun modèle ne peut écrire
« un portefeuille de 15 à 25 entreprises représentant 50 à 75 millions d'euros »
si le profil dit « gestion des flux » — et s'il l'essaie, le garde-fou le rejette
à raison. Les six faits chiffrés des lettres personnelles du candidat étaient
absents du profil, et son expérience la plus pertinente tenait en 133 caractères.
`situation_actuelle` et `disponibilite` ont été ajoutés pour la même raison :
sans le second, le prompt avait **interdiction** d'annoncer une disponibilité,
faute de pouvoir la vérifier. Ni l'un ni l'autre ne figure dans les blocs
d'import — un CV ne les contient pas, les demander au modèle le ferait inventer.
`annees_experience` s'ajoute à cette liste pour une troisième raison : les
dates d'un CV sont souvent partielles (« Septembre 2021 » sans fin) et les
périodes se chevauchent — une somme automatique se tromperait sans le dire.
Le champ est borné 0–60 côté schéma **et** côté saisie : hors bornes, c'est
l'enregistrement du profil entier qui échouait en 422.

**Un critère ajouté au back doit l'être aussi dans `BarresScore.tsx`.** Le
composant n'affiche que les clés qu'il connaît : les deux nouveaux critères y
étaient invisibles, donc le score baissait sans que rien ne l'explique. C'est
le genre d'oubli qu'aucun test backend n'attrape.

**Le CV ciblé : le modèle propose, le code vérifie chaque puce**
(`documents/ciblage.py`). Reprendre le vocabulaire de l'annonce quand il désigne
la même chose est l'optimisation ATS honnête ; ajouter ce qu'elle réclame et que
le candidat n'a pas fait est une fausse déclaration. Chaque puce réécrite est
refusée si elle introduit un nombre, un nom propre ou un sigle absent de
l'original, un mot porteur de sens qui n'en soit ni un synonyme métier, ni un mot
de la même famille, ni un mot générique ; si elle s'allonge de plus d'un tiers ;
si elle recopie l'annonce. Une puce refusée retombe sur l'originale et le refus
est consigné — un CV ciblé à moitié vaut mieux qu'un CV qui ment à moitié.

Le contrôle a été **calibré sur les puces réelles** avant d'être branché : quatre
mensonges écrits à la main (IFRS 9, Bloomberg, « provisionnement »,
« contreparties », un chiffre changé) sont tous bloqués. Deux réécritures honnêtes
étaient d'abord refusées pour des mots grammaticaux (« mise en place »,
« contre ») : d'où `NEUTRES`. « impayés » pour « non-paiement » reste refusé,
exprès — accepter un sens voisin que la table métier ne connaît pas, c'est ouvrir
la porte au glissement.

Le résumé ciblé ne peut citer de chiffre **que du profil** : « 5 ans
d'expérience » figure dans l'offre, et c'est précisément pourquoi il ne peut pas
figurer dans le résumé. Il est impersonnel — un « je » ou un « votre » le fait
refuser.

**Le ciblage a un second tour, qui nomme la faute.** Au premier dossier réel,
Sonnet 5 a proposé cinq réécritures et les cinq ont été refusées : il prêtait
aux puces les exigences de l'annonce (« contrôle », « mesure »,
« identification ») — refus justes. Mais il mêlait dans une même puce un ajout
abusif et une reformulation honnête, et la puce entière partait. Le second tour
renvoie les seules puces refusées avec leurs motifs : au dossier suivant, trois
puces réécrites dont deux grâce à la correction, et les deux restantes toujours
refusées pour les mêmes mots. C'est la méthode qui marche sur la lettre — un
modèle obéit quand on lui nomme la faute.

**Le ciblage est demandé une seule fois**, avant la boucle qui tient le CV sur une
page : dans la boucle, il serait redemandé — et payé — jusqu'à quatre fois. Un
échec d'appel n'empêche rien, le CV part avec les puces du profil.

**« Ce que verra le recruteur »** (`documents/correspondance.py`, fiche d'une
offre) : le titre qui figurera sous le nom, les termes récurrents de l'annonce
couverts et manquants, un taux (Jobscan vise 75 à 80 %), les langues et
l'ancienneté exigées, et une alerte quand la description est tronquée (Adzuna
coupe à 500 caractères). Pur code, aucun appel. Le taux n'est pas un score de
plus : le score dit si l'offre convient, le taux dit si le CV parle la langue de
l'annonce. Les pluriels comptent — « bancaires » était donné manquant à un
profil qui dit « banque », faute d'être dans la famille de synonymes.

**`mots_cles_non_couverts`** (`scoring/couverture.py`) : les termes récurrents de
l'annonce qu'aucun élément du profil ne recouvre, synonymes compris. Le nom de
l'employeur et le lieu en sont exclus : l'avertissement annonçait « caixa,
depositos, geral, paris » comme des compétences à combler. Ce n'est pas
un jugement sur l'offre — le score s'en charge — mais sur le profil. Répété sur
vingt candidatures, il dessine la compétence à combler. Pur code, aucun appel.

**`generation.json`** est écrit dans chaque dossier : essais, fautes de chaque
tentative, défauts restants. Quand une lettre est mauvaise, c'est le seul moyen
de savoir quelle étape a fauté — ce n'est pas du confort de développeur.

---

## Recherches enregistrées

Un profil ne se résume pas à un jeu de mots-clés : « analyste risques »,
« middle office » et « V.I.E finance » se cherchent en même temps, parfois sur
des pays différents. Chaque `Recherche` active est jouée à chaque scan, manuel
comme automatique.

Trois règles :

- **Un seul `ScanRun` pour toutes les recherches.** C'est une recherche du point
  de vue de l'utilisateur ; l'historique n'a pas à se remplir d'une ligne par
  mot-clé.
- **Pays et contrats vides = ceux du profil.** Une recherche n'a pas à répéter
  les préférences quand elle ne les restreint pas.
- **Une offre est retenue dès qu'UNE recherche l'accepte.** Une mission V.I.E au
  Canada ne doit pas être jetée parce que la recherche « CDI Paris » l'exclut.

La déduplication passe **avant** le filtrage : plusieurs recherches ramènent
souvent la même annonce, et la compter une fois par recherche gonflerait le
nombre de rejets sans rien signifier.

Sans aucune recherche définie, on retombe sur le profil — l'application reste
utilisable avant qu'on en ait créé une. Les mots-clés de `config.yaml` sont ceux
du propriétaire : un autre compte se rabat sur son titre visé, et sans titre il
n'a rien à chercher (409) — jamais sur la recherche d'un autre.

Chaque recherche appartient à un compte ; son nom est unique **par compte**.

---

## Écran Offres

L'API sert **60 offres par défaut** (`limite`, plafond 500) : l'écran affiche
« X affichées sur Y » et un bouton pour élargir la fenêtre. Sans ce compteur,
l'interface annonçait « 448 offres » en n'en montrant que soixante.

La zone de recherche est **temporisée** (250 ms) : chaque requête en déclenche
quatre côté base (la liste plus les trois compteurs de facettes), et une frappe
non temporisée en lançait autant que de caractères tapés.

Les jokers de `LIKE` sont **échappés** (`echapper_like`) : sans cela, taper
« % » remontait toute la base et « middle_office » matchait n'importe quel
caractère à la place du souligné.

---

## Offres retirées du site

Chaque scan qui **revoit** une annonce rafraîchit `Offer.derniere_vue_le` : un
doublon n'est pas du bruit, c'est la preuve que l'offre tient encore. Passé
`offres.expiree_apres_jours`, elle est signalée « expirée ? » et peut être
masquée — jamais supprimée : une source en panne ne doit pas faire disparaître
des offres valides.

---

## Relances

`candidatures.relance_apres_jours` : une candidature au statut **« Envoyée »**
et sans nouvelle depuis ce délai porte un badge « à relancer ». Les autres
statuts sont exclus — relancer un refus n'a aucun sens.

---

## Sauvegarde

`services/sauvegarde.py` copie la base à chaque démarrage dans
`data/sauvegardes/`, et n'en garde que sept. La copie passe par l'API `backup`
de SQLite, **jamais par un `copy` de fichier** : en WAL, les écritures récentes
vivent dans un journal annexe et une copie brute serait amputée.

Le hook `hooks/pre-commit` (activé par `core.hooksPath`) refuse un commit dont
les tests échouent.

---

## Suivi des candidatures

`exports/excel.py` produit le **justificatif de recherche d'emploi** envoyé tel
quel à France Travail : en-têtes français, une ligne par candidature, dates au
format `jj/mm/aaaa` (de vraies dates Excel, triables), ligne de titre figée,
filtres automatiques. Ni formule ni onglet technique — un agent doit pouvoir le
lire sans explication.

La **reprise** (`lire`) se repère aux en-têtes et non aux positions : un fichier
retouché à la main reste importable. Elle ne crée jamais de candidature — une
candidature sans offre en base serait un fantôme ; les lignes sans correspondance
sont signalées. L'appariement se fait sur l'URL de l'offre, puis sur
entreprise + poste normalisés.

---

## Scan automatique

**DreamJob n'est pas un serveur** : il ne tourne que pendant que l'utilisateur
l'a ouvert. Un simple « tous les jours à 7 h 30 » manquerait donc son rendez-vous
dès que l'application est fermée, sans que rien ne le rattrape.

D'où deux déclencheurs, dans `scheduler.py` :

- **l'heure quotidienne** (`planification.heure`), utile si l'application reste
  ouverte ;
- **le rattrapage au démarrage** : si aucun scan n'a *abouti* depuis
  `rattrapage_apres_heures`, un scan part quelques secondes après l'ouverture.

« Abouti » exclut les scans en échec : sinon une panne de source ferait croire
que la veille est à jour et le rattrapage ne se déclencherait jamais. Un scan
partiel, lui, compte — les offres des sources valides sont bien arrivées.

Trois réglages non négociables, chacun corrigeant une panne silencieuse :

- **`misfire_grace_time`** à six heures. APScheduler abandonne par défaut une
  exécution en retard de plus d'**une seconde** : sur un poste qui dort la nuit,
  le rendez-vous quotidien serait systématiquement perdu, sans trace.
- **Le rattrapage utilise l'heure du fuseau du planificateur**, pas
  `datetime.now()`. Une heure naïve est relue comme une heure de Paris : sur une
  machine réglée ailleurs, elle tomberait dans le passé et ne partirait jamais.
- **Aucun rattrapage sur une base vierge.** La toute première recherche revient
  à l'utilisateur — sortir sur le réseau avant qu'il ait vu l'écran Profil
  serait une initiative qu'il n'a pas demandée.

Le scan planifié joue les recherches **de tous les comptes**, en un seul
`ScanRun` sans propriétaire (`utilisateur_id` vide). Une requête identique
demandée par deux comptes n'est jouée qu'une fois. Le scoring et le résumé du
matin suivent, compte par compte.

Le scan automatique prend ses **pays et contrats dans le profil**, pas dans
`config.yaml` : ce que l'utilisateur a coché l'emporte sur un repli, sinon un
scan nocturne filtrerait sur « France » pendant que le profil accepte quatre
pays.

Le badge compte les offres **arrivées à la dernière recherche** et pas encore
ouvertes — pas toutes les offres jamais consultées, qui le bloqueraient à
« 99+ » pendant des mois. Le total reste disponible dans `jamais_vues`.

`executer_scan` n'a pas le droit de laisser remonter une exception : le
planificateur resterait muet jusqu'au prochain redémarrage.

---

## Veille

**Arriver parmi les premiers.** Le scan quotidien trouve une offre le lendemain
au mieux ; mesuré sur la base locale, le retard médian entre la publication et
la découverte était de 6,6 jours chez France Travail. Un recruteur trie souvent
au fil de l'eau. La veille (`services/veille.py`) joue donc, toutes les
`veille.intervalle_minutes` entre `heure_debut` et `heure_fin`, une recherche
légère — **les seules offres du jour** —, note ce qui arrive, et envoie **une
alerte par offre verte** (`notification.alerter`) : une par offre, pour qu'un
clic ouvre sa fiche (`Click` → `/offres/{id}`), et sonnerie forcée au-dessus
de 90.

**On ratisse plus large que les recherches enregistrées.** Repérer une
nouveauté ne coûte qu'une requête ; le score trie derrière. S'ajoutent donc les
intitulés du CV que `cible.construire` a déjà pesés — titre visé, postes,
mots-clés d'expérience, secteurs —, jamais les diplômes (« Master 2 Finance »
n'est pas un poste), sans répéter une recherche, plafonnés à
`requetes_du_cv_max` par compte.

**Pas toutes les sources.** Adzuna plafonne à 2 500 appels par mois, et le scan
quotidien en prend déjà environ 1 500 ; DogFinance est limité à quarante pages
par jour pour une raison juridique. Les deux restent au scan du matin. France
Travail et Civiweb n'ont pas ce problème.

**Une offre n'est signalée qu'une fois**, alerte ou résumé :
`ScoreOffre.alertee_le`. Le résumé du matin reprend sur une journée entière
(`FENETRE_RESUME`) ce qui est vert et pas encore signalé — la nuit, et le
surplus d'une journée où le plafond d'alertes (`alertes_par_jour_max`) a été
atteint. Une sonnerie toutes les dix minutes apprend à les ignorer toutes.

**La veille n'est pas le scan du matin.** Elle crée bien un `ScanRun`
(`declenche_par = "veille"`), mais `dernier_scan_abouti` l'ignore : comptée, elle
aurait réduit le badge « nouvelles » à la dernière demi-heure, et empêché le
rattrapage du matin, qui interroge toutes les sources. Ses `ScanRun` sont
oubliés après `conserver_jours` — trente par jour noieraient l'historique ; les
offres trouvées restent.

**Un scan et une veille ne tournent jamais ensemble** (`scheduler._VERROU_SCAN`) :
ils écriraient les mêmes offres en même temps. Le scan attend ; la veille passe
son tour, la suivante reprendra ce que le scan n'aura pas déjà trouvé.

Elle ne prépare aucun dossier : choisir où postuler reste à l'utilisateur.
En local, elle ne tourne que pendant que l'application est ouverte, et n'alerte
que si un sujet ntfy est renseigné.

---

## Hébergement

Un VPS (Hetzner CX23, ~7 €/mois) joignable **uniquement** par Tailscale.
`deploiement/GUIDE.md` déroule l'installation ; `installer-serveur.sh` prépare
une Ubuntu neuve, `deployer.sh` envoie le dernier commit depuis le PC — sans
passer par GitHub — et, au premier déploiement, la base, le modèle de CV et les
dossiers. Le `.env` n'est jamais envoyé par script : les secrets se déposent à
la main.

**Le mode serveur est une variable d'environnement de l'image**
(`DREAMJOB_MODE=serveur`, fixée dans le `Dockerfile`), pas un réglage de
`config.yaml` : un conteneur lancé sans elle resterait ouvert. Il rend la
connexion obligatoire, les cookies `Secure`, et supprime l'ouverture du dossier.

**Trois barrières, et aucune ne suffit seule.** Le conteneur n'écoute que sur
`127.0.0.1` ; le pare-feu n'ouvre que SSH et l'interface `tailscale0` ;
l'application exige une session. `tailscale serve` relaie en HTTPS, avec un
certificat valide, sur le réseau privé.

**Le verrou est un intergiciel, pas une dépendance par routeur**
(`api/acces.verrou`) : une route oubliée serait une route ouverte. Tout `/api/`
est fermé sans session, sauf `/api/acces/*` et `/api/sante`. La page elle-même
se charge — il faut bien afficher le formulaire. Pas d'inscription par l'API :
un compte se crée en ligne de commande sur le serveur (`python -m app.compte`),
le mot de passe saisi sans écho.

**Rien de secret n'est stocké en clair.** Mots de passe en scrypt
(`hashlib`, aucune dépendance ajoutée), sel aléatoire ; sessions stockées par
l'empreinte SHA-256 de leur jeton — une sauvegarde égarée n'ouvre aucune
session. Un seul message pour « adresse inconnue » et « mauvais mot de passe »,
et le même coût de calcul dans les deux cas : ni le texte ni la durée ne disent
quels comptes existent. Dix échecs en un quart d'heure bloquent l'adresse.

**L'API sert l'interface compilée** : un seul processus, un seul port. Toute
adresse qui n'est ni `/api/` ni un fichier de `frontend/dist` renvoie
`index.html` ; `resolve()` puis vérification du parent empêchent
`/..%2F..%2F.env` de sortir du dossier — vérifié.

**Les documents se téléchargent** (`GET /api/offres/{id}/documents/{nom}`) :
un simple nom, d'un type servi (PDF, Word), présent dans le dossier de CETTE
offre. Le dossier se retrouve par l'`offre.json` qu'il archive quand aucune
candidature ne le retient encore.

**Carlito, sinon le CV change de page.** Le modèle de CV et la lettre
n'utilisent que Calibri, absente de Linux. Carlito a les mêmes métriques :
sans elle, LibreOffice substitue une autre police, les lignes changent de
longueur, et la mesure « une page » n'est plus celle de Windows.

**Les fichiers exécutés sur le serveur sont en LF** (`.gitattributes`). Un
script bash en CRLF échoue sur `bash
` ; et le `sed -i` de Git Bash réécrit
en mode texte Windows — il remet les CRLF qu'on croyait retirer.

**Le résumé du matin** (`services/notification.py`) part après le scan
planifié, vers ntfy, seulement s'il y a des offres vertes jamais ouvertes ni
déjà signalées par la veille : une
alerte quotidienne « rien de nouveau » apprend à ignorer les autres. Chaque
compte a son sujet, saisi dans son profil ; `NTFY_SUJET` ne vaut que pour le
propriétaire — un ami sans sujet ne reçoit rien, surtout pas sur le téléphone
d'un autre. Le sujet tient lieu de mot de passe ; ne transitent que des
intitulés, des employeurs et des scores.

**Les tests n'agissent plus sur la vraie base.** Le client de test démarrait
l'application complète : `creer_tables()` avait créé les tables de comptes
dans la base réelle — l'autogénération Alembic est alors sortie **vide** — et
chaque test sauvegardait cette base et démarrait le planificateur. Le démarrage
est désormais neutralisé dans `conftest.py`, et la migration des comptes crée
ses tables seulement si elles manquent, pour passer sur les deux bases.

---

## Comptes

**Une offre est commune, sa note ne l'est pas.** Le score dépend du profil, et
« déjà vue » de celui qui regarde : les deux vivent dans `ScoreOffre`
(utilisateur, offre), avec la date d'entrée dans le fil. **Une ligne y est
aussi l'appartenance au fil** : une offre n'apparaît chez quelqu'un que si
l'une de SES recherches l'a ramenée. Toutes les requêtes partent d'une jointure
interne sur ce fil ; une offre d'un autre fil répond 404, même demandée par son
identifiant. L'ami qui cherche en marketing ne parcourt pas deux mille offres
de finance, et ne voit pas ce que cherchent les autres.

**Le compte vient du verrou, jamais du client.** `verrou` établit l'utilisateur
à partir du cookie et le pose dans `request.state` ; la dépendance
`utilisateur_courant` le relit. Toute route qui touche une donnée personnelle
en dépend. Une ressource d'un autre compte répond **404, pas 403** : on ne
confirme même pas qu'elle existe. En local, sans connexion, c'est le
propriétaire qu'on sert.

**Le propriétaire** est le premier compte. La migration rattache les données
d'avant les comptes à un compte « local » sans mot de passe (qui ne vérifie
jamais) ; le premier `python -m app.compte creer` le reprend, avec tout ce
qu'il porte. Lui seul reçoit les sources `personnel: true` — DogFinance, dont
les CGU ne tolèrent qu'un usage personnel : les recherches des amis n'y sont
jamais envoyées, même demandées explicitement. Lui seul n'a pas de budget.

**Le budget d'un ami** (`comptes.budget_mensuel_usd`, 2 $ par mois, soit
environ vingt-cinq dossiers) : c'est la clé du propriétaire qui paie. Chaque
appel payant est chiffré et imputé (`DepenseLlm`) — y compris d'une génération
qui échoue en route, les jetons étant facturés quand même — et l'import de CV
compte comme un dossier. Au-delà : 429, jusqu'au 1er du mois.
`python -m app.compte budget` le change, `lister` montre qui dépense quoi.

**Les dossiers d'un ami vivent à part** : `candidatures/comptes/<id>/`. Le
propriétaire garde la racine — ses dossiers existants ne bougent pas — et la
recherche d'un dossier par `*/offre.json` ne descend pas jusqu'à ceux des autres.

**La migration ne reconstruit aucune table.** La base active les clés
étrangères : le mode « batch » d'Alembic — copier `offer`, supprimer l'ancienne
— échouerait, d'autres tables la référençant. Tout passe par `ADD COLUMN`
(une clé étrangère s'ajoute tant que la valeur par défaut est NULL), `DROP
COLUMN` après suppression des index, et des index. Vérifiée sur une copie de la
vraie base : 4 486 offres, autant de notes, somme des scores et offres déjà
ouvertes identiques ; `alembic check` ne voit aucun écart, ni sur la copie ni
sur une base neuve.

**L'isolation est prouvée, et la preuve est vérifiée.** `test_comptes.py`
passe par l'API, connecté tour à tour comme chaque compte. Retirer le filtre
par compte des offres et des candidatures fait échouer trois de ses tests :
ils attrapent bien la fuite qu'ils décrivent.

**Deux tests lisaient encore la vraie base.** L'un démarrait l'application
complète sans la neutralisation de `conftest.py` : il a créé les deux nouvelles
tables dans la base de l'utilisateur (vides, et la migration les accepte déjà
présentes). L'autre, `etat()` du planificateur, y cherchait le dernier scan. Les
deux sont corrigés ; ils passaient jusque-là parce que la vraie base était à jour.

**Ce que le propriétaire voyait chez l'ami, avant correction** : le bandeau
« dernière recherche — 1 415 nouvelles offres » était le sien. `etat()` compte
désormais les entrées dans le fil du compte, et tous les scans d'avant les
comptes, planifiés compris, sont rattachés au propriétaire.

---

## Mode dégradé

Sans `ANTHROPIC_API_KEY`, l'application démarre quand même : scoring lexical
seul, pas d'import de CV, pas de lettre générée. L'état est visible sur
`/api/sante` et affiché en bandeau dans l'interface.

Sans LibreOffice, les documents sont générés en Word uniquement — même principe.

---

## Avancement

- [x] **1.** Squelette, modèles, migrations, `dev.ps1`
- [x] **2.** Import du CV → profil structuré + écran d'édition
- [x] **3.** Connecteur France Travail — validé en réel : 47 offres, second scan identique = 0 doublon créé
- [x] **4.** Scoring + tests + écran Offres — **sans LLM**, 137 tests au vert
- [x] **5.** Écran Détail + détail du score — bouton « Postuler » compris
- [x] **6.** Génération CV/lettre Word + PDF — modèle préservé, anti-invention bloquant
- [x] **7.** Écran Candidatures + export Excel — justificatif France Travail
- [x] **8.** Connecteurs — France Travail, Civiweb (V.I.E) et Adzuna actifs ; trois sources refusées, motifs consignés
- [x] **10.** Recherches enregistrées multiples, jouées ensemble
- [x] **9.** Scan planifié quotidien + rattrapage au démarrage + badge « X nouvelles offres »
- [x] **11.** Connecteur DogFinance (spécialisé finance) — validé en réel : 63 offres, 12 vertes, descriptions médianes à 2 300 caractères ; prélèvement plafonné à 40 pages par scan
- [x] **12.** Ce que voit le recruteur — intitulé nettoyé (45 % des offres portaient « (H/F) »), élision de l'objet, fichiers et métadonnées au nom du candidat, expériences et formations dans l'ordre des dates, accord saisi et jamais déduit
- [x] **13.** Rédaction payante — lettre par Opus 5.5, CV ciblé par Sonnet 5 sous contrôles puce par puce, coût de chaque dossier dans `generation.json`, panneau « Ce que verra le recruteur »
- [x] **14.** Hébergement prêt — comptes et verrou, téléchargement des documents, interface servie par l'API, image Docker (Carlito), résumé du matin par ntfy, scripts d'installation et de déploiement. Déploiement réel : à faire
- [x] **15.** Un compte par personne — profil, recherches, notes, candidatures, documents et notifications séparés ; offres partagées mais fil propre à chacun ; DogFinance réservé au propriétaire ; budget mensuel des amis ; migration vérifiée sur la vraie base
- [x] **16.** Score refait et mesuré — tout le CV lu, métier reconnu dans les deux sens, contenu étalonné, niveau / diplôme / certifications / statut lus dans l'annonce, pertinence × accessibilité × conditions, points rédhibitoires, explication en lignes, recalcul automatique ; 182 offres étiquetées, top 20 : 6 → 20 offres pertinentes
- [x] **17.** Veille — les offres du jour toutes les demi-heures en journée, recherches enregistrées et intitulés du CV, une alerte ntfy par offre verte (clic vers la fiche), plafond quotidien, une offre signalée une seule fois ; Adzuna et DogFinance tenus à l'écart
- [x] **18.** Sites des employeurs — 228 employeurs repérés, 82 actifs par onze connecteurs (un par logiciel, plus le plan du site + JobPosting), robots.txt selon la RFC 9309 et Crawl-delay, refus motivés ; branchés sur la veille
