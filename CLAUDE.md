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

`llm.fournisseur` choisit entre `ollama` (local, gratuit, par défaut) et
`anthropic`. **`ClientLlm._appeler_fournisseur` est le seul endroit où ce choix
se fait** : cache, validation Pydantic et messages d'erreur sont communs. Avant
cet aiguillage, l'import de CV était resté câblé sur Anthropic alors que la
lettre savait déjà tourner en local.

**L'import de CV se fait en quatre passes** (identité, expériences, formations,
compétences). Un modèle local de 7 milliards de paramètres ne tient pas quatorze
champs en un seul appel : il range le nom dans le titre visé et rend zéro
compétence. Découpé, il devient exploitable. Chaque passe a sa propre entrée de
cache (`variante`) : une passe qui échoue ne fait pas perdre les autres.

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

**Synonymes métier** (`scoring/synonymes.py`) : les offres de ce domaine sont
massivement bilingues. Sans table d'équivalences, « risques de crédit » ne
rencontre jamais « credit risk » et la moitié du marché est écartée.

**Langue : deux questions distinctes.** Celle dans laquelle l'annonce est
écrite, et celles qu'elle **exige** (`langues_exigees`). Une offre en français
réclamant « anglais courant » était jugée parfaitement accessible. C'est
l'exigence la plus dure qui décide. Une langue seulement citée, sans marqueur
d'exigence à proximité, n'est pas retenue : mieux vaut manquer une exigence que
d'écarter une offre à tort.

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
utilisable avant qu'on en ait créé une.

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
