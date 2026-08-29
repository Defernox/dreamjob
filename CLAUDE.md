# DreamJob

Application **locale** de recherche d'emploi : agréger les offres → les scorer →
générer CV et lettre → postuler → tracer les candidatures pour France Travail.

Mono-utilisateur, aucun déploiement. Rien ne sort de la machine sauf les appels
à l'API Anthropic et aux sources d'offres.

---

## Commandes

| Objectif | Commande |
|---|---|
| **Installer** (une seule fois) | `.\setup.cmd` |
| **Lancer** (API + interface) | `.\dev.cmd` |
| Tests backend | `cd backend; .\.venv\Scripts\python.exe -m pytest` |
| Typage frontend | `cd frontend; npx tsc --noEmit` |
| Nouvelle migration | `cd backend; .\.venv\Scripts\alembic.exe revision --autogenerate -m "message"` |
| Appliquer les migrations | `cd backend; .\.venv\Scripts\alembic.exe upgrade head` |

Interface : http://localhost:5173 — API : http://127.0.0.1:8000/docs

**Pourquoi `.cmd` et non `.ps1`.** Windows bloque par défaut l'exécution des
scripts PowerShell (`ExecutionPolicy`). Les `.cmd` échappent à cette
restriction : ils appellent le `.ps1` avec un contournement valable pour ce seul
processus. Aucun réglage de sécurité de la machine n'est modifié — et il ne faut
pas en modifier : c'est une protection légitime.

`make` fonctionne aussi (`make dev`, `make test`) si GnuWin32 est dans le PATH.

---

## Arborescence

```
DreamJob/
├─ config.yaml          réglages : poids du scoring, sources actives, chemins
├─ .env                 secrets uniquement (jamais versionné)
├─ setup.cmd / dev.cmd  installation / lancement (appellent les .ps1)
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
│     ├─ connectors/    base · http (débit, cache) · registry · une source = un fichier
│     ├─ services/      dedup (hash) · scan (orchestration)
│     ├─ scoring/       extraction LLM (cachée) + calcul du score (pur code)
│     ├─ documents/     docx_outils · cv_render · lettre · pdf · dossier
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

## Conventions

**Langue.** Interface, messages d'erreur, noms de champs en base et
identifiants de code : **en français**. Les mots-clés techniques restent en
anglais (`Offer`, `hash`, `score`).

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
autogénérations produisent des `sqlmodel.sql.sqltypes.AutoString`.

---

## Les trois règles à ne pas casser

**1. Le score n'appelle JAMAIS de LLM.**
Scorer, ce n'est pas *extraire* : c'est comparer une offre à un profil déjà
connu. Les cinq critères se calculent en pur code — compétences par appariement
lexical, secteur par le **code ROME** que fournit la source, pays et contrat déjà
structurés, langue par détection statistique. Déterministe, rejouable, gratuit.
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

Deux modèles, deux usages — réglés dans `config.yaml` :

| Réglage | Modèle | Appelé | Pourquoi |
|---|---|---|---|
| `modele_extraction` | *(inutilisé)* | jamais | le scoring est en pur code |
| `modele_redaction` | `claude-opus-5` | import de CV, lettre | rare et à fort enjeu |

**L'application doit rester gratuite.** Le compte Anthropic n'a pas de crédits :
la rédaction passe par **Ollama en local** (`mistral:7b`, RTX 3060, ~100 tok/s).
Anthropic reste branchable pour qui veut une meilleure qualité de lettre.
Attention : un modèle local invente plus facilement — le garde-fou
anti-invention doit **rejeter et régénérer**, pas seulement avertir.

Une clé « liée à une identité » exige en plus `ANTHROPIC_WORKSPACE_ID` dans
`.env` — sans lui, l'API répond `400 anthropic-workspace-id is required`.
C'est le cas de la clé utilisée ici.

Un compte sans crédits répond `400 Your credit balance is too low` : la clé est
valide, l'authentification passe, seul l'appel échoue. Ces deux pannes sont
traduites en français dans `app/llm/client.py` et couvertes par des tests.

Les erreurs de l'API remontent **telles quelles** à l'utilisateur
(`app/llm/client.py`) : reformuler la cause fait perdre du temps au diagnostic.

---

## Le score en détail

| Critère | Source du signal | Particularité |
|---|---|---|
| Compétences 35 % | appariement lexical profil ↔ texte de l'offre | 60 % vient de la **meilleure** compétence ancrée, 40 % du nombre d'autres compétences (plafonné à 3). On mesure la **qualité** de la correspondance, jamais le taux de couverture : une annonce ne cite jamais tout un profil |
| Secteur 25 % | intitulé + `romeLibelle` + famille ROME | reconnu dans l'intitulé = signal fort, dans le corps = 60 % |
| Pays 15 % | champ structuré de la source | binaire. **Attention** : France Travail publie aussi hors de France (Luxembourg surtout). Le pays se déduit du préfixe de département (« 75 - Paris ») ou du nom de pays dans le libellé — tout étiqueter « France » fausserait le critère |
| Langue 15 % | mots-outils (`scoring/langue.py`) | texte trop court ⇒ non évalué, jamais pénalisé |
| Contrat 10 % | champ structuré | l'ordre de `contrats_acceptes` porte la préférence : de 100 à 60, jamais 0 pour un contrat accepté |

Deux règles qui évitent des scores absurdes :

- **Critère non évaluable ⇒ poids redistribué.** Un profil sans pays acceptés ne
  doit ni tout mettre à 0 ni tout gonfler à 100.
- **Plafond hors cible** (`plafond_hors_cible`, 25 par défaut). Si compétences
  *et* secteur sont à 0, l'offre est plafonnée : pays, langue et contrat sont des
  filtres administratifs, ils ne doivent pas faire remonter un poste sans rapport.

Les mots génériques d'une compétence (« gestion », « analyse ») pèsent 0,4 contre
1 pour les mots spécifiques : dans « gestion de trésorerie », c'est
« trésorerie » qui compte.

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
| Talent.com | **refusé** | `robots.txt` interdit `/services/api-new/search` et `/search-jobs/*` |
| HelloWork | **refusé** | `robots.txt` interdit `/fr-fr/emploi/recherche.html` et `Disallow: /*?` |
| Welcome to the Jungle | **refusé** | `robots.txt` interdit `*/jobs?query=*` ; API réservée aux partenaires |
| APEC | en attente | `robots.txt` permissif, mais le sitemap ne publie que des pages de recherche et il n'existe pas d'API |

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

**L'anti-invention est bloquant, pas indicatif.** `lettre.py` compare chaque nom
propre et chaque année de la lettre au profil et à l'offre ; ce qui est inconnu
déclenche une régénération, en nommant l'erreur au modèle. Après N essais
(`llm.tentatives_anti_invention`), la lettre est refusée : le CV part seul,
l'avertissement est remonté. Mieux vaut pas de lettre qu'une lettre qui ment.

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

`executer_scan` n'a pas le droit de laisser remonter une exception : le
planificateur resterait muet jusqu'au prochain redémarrage.

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
- [x] **9.** Scan planifié quotidien + rattrapage au démarrage + badge « X nouvelles offres »
