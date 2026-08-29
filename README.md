# DreamJob

Application **locale** de recherche d'emploi : agréger les offres, les scorer,
générer CV et lettre de motivation adaptés, puis tracer les candidatures pour
France Travail.

Mono-utilisateur, sans déploiement. Les données restent sur la machine : la base
SQLite, les dossiers de candidature et les caches ne sortent jamais du poste.

## Ce que ça fait

1. **Agréger** — chaque source d'offres est un connecteur derrière une interface
   commune. France Travail (API officielle Offres d'emploi v2) en premier.
2. **Scorer** — cinq critères pondérés : compétences, secteur, pays, langue,
   contrat. Le calcul est du **code pur, sans appel à un modèle de langage** :
   déterministe, rejouable, gratuit. Changer un poids recalcule tout sans
   réinterroger quoi que ce soit.
3. **Générer** — CV rendu depuis un modèle Word personnel (jamais depuis un
   document vierge, la mise en page du modèle est la référence) et lettre de
   motivation rédigée par un modèle local.
4. **Tracer** — tableau de suivi et export Excel présentable à France Travail
   comme justificatif de recherche.

## Les règles qui structurent le code

- **Le scoring n'appelle jamais de LLM.** Comparer une offre à un profil connu
  est un problème d'appariement, pas d'extraction. Un test casse si un appel
  réseau réapparaît dans cette couche.
- **Le LLM n'invente rien.** Chaque nom propre et chaque date d'une lettre est
  comparé au profil et à l'offre ; l'inconnu déclenche une régénération, puis un
  refus. Mieux vaut pas de lettre qu'une lettre qui ment sur un parcours.
- **Un connecteur qui casse n'interrompt jamais les autres.** L'erreur est
  consignée et le scan continue.
- **Rien ne s'appelle deux fois.** Toute réponse d'un modèle est mise en cache :
  relancer un scan ne coûte rien.

## Pile technique

Python 3.11+, FastAPI, SQLModel, Alembic · React, Vite, TypeScript, Tailwind,
TanStack Query · python-docx et LibreOffice pour les documents · openpyxl pour
l'export · Ollama en local, ou l'API Anthropic.

## Installation

```powershell
.\setup.ps1   # une seule fois
.\dev.ps1     # lancement quotidien
```

Interface sur http://localhost:5173, API sur http://127.0.0.1:8000/docs.

Les réglages sont dans `config.yaml`, les secrets dans `.env` (voir
`.env.example`). L'application démarre même sans clé d'API ni LibreOffice, en
mode dégradé, et affiche ce qui manque.

`CLAUDE.md` documente l'architecture, les conventions et les pièges rencontrés.

## Licence

Projet personnel, publié à titre documentaire.
