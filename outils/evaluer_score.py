"""Mesure la qualité du classement contre des étiquettes posées à la main.

    backend\\.venv\\Scripts\\python.exe outils\\evaluer_score.py            (depuis la racine)
    backend\\.venv\\Scripts\\python.exe outils\\evaluer_score.py --detail   (+ le top 25)

Un réglage du score se MESURE, il ne se devine pas : c'est ainsi qu'a été
conçue la version 7 (voir CLAUDE.md, « Le score en détail »). Le script lit la
base en LECTURE SEULE, calcule le score de toutes les offres du propriétaire
avec le code du dépôt, et compare le classement aux étiquettes
d'`etiquettes_score.py` :

- **concordance** : la part des paires d'offres d'étiquettes différentes que le
  score range dans le bon ordre (0,5 = hasard) ;
- **NDCG@20 / @50** : la qualité du haut du classement, celui qu'on lit ;
- le nombre d'offres pertinentes et hors sujet dans le top 20 ;
- la note moyenne par niveau d'étiquette — elle doit décroître.

Rien n'est écrit, nulle part.
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from etiquettes_score import ETIQUETTES  # noqa: E402

from app.config import reglages  # noqa: E402
from app.models import Offer, Profile  # noqa: E402
from app.scoring.cible import construire  # noqa: E402
from app.scoring.corpus import Corpus  # noqa: E402
from app.scoring.extraction import extraire  # noqa: E402
from app.scoring.score import calculer, etalonner  # noqa: E402

CHAMPS_OFFRE = ("id", "source", "source_id", "url", "titre", "entreprise", "lieu", "pays",
                "type_contrat", "date_publication", "date_recuperation", "description_brute",
                "hash", "raw", "derniere_vue_le")
JSON_PROFIL = ("secteurs", "langues", "pays_acceptes", "contrats_acceptes", "skills",
               "experiences", "formations")


def _date(valeur):
    return datetime.fromisoformat(valeur) if valeur else None


def charger():
    base = f"file:{reglages().chemins.db.as_posix()}?mode=ro"
    c = sqlite3.connect(base, uri=True)
    c.row_factory = sqlite3.Row
    colonnes = {r[1] for r in c.execute("PRAGMA table_info(profile)")}
    # Le propriétaire, sur une base à comptes ; le seul profil, sinon.
    if "utilisateur_id" in colonnes:
        ligne = c.execute("SELECT p.* FROM profile p JOIN utilisateur u ON u.id = p.utilisateur_id "
                          "WHERE u.proprietaire = 1").fetchone()
        filtre = " AND utilisateur_id = (SELECT id FROM utilisateur WHERE proprietaire = 1)"
    else:
        ligne, filtre = c.execute("SELECT * FROM profile ORDER BY id").fetchone(), ""
    p = dict(ligne)
    for k in JSON_PROFIL:
        p[k] = json.loads(p[k] or "[]")
    profil = Profile(**{k: v for k, v in p.items() if k in Profile.model_fields
                        and k not in ("created_at", "updated_at", "cv_importe_le")})
    offres = []
    for r in c.execute(f"SELECT {', '.join(CHAMPS_OFFRE)} FROM offer"):
        d = dict(r)
        d["raw"] = json.loads(d["raw"] or "{}")
        for k in ("date_publication", "date_recuperation", "derniere_vue_le"):
            d[k] = _date(d[k])
        offres.append(Offer(**d))
    recherches = [json.loads(r[0]) for r in c.execute(
        f"SELECT mots_cles FROM recherche WHERE active = 1{filtre}")]
    return profil, offres, recherches


def scorer(profil, offres, recherches) -> dict[int, float]:
    signaux = {o.id: extraire(o) for o in offres}
    corpus = Corpus.depuis(signaux.values())
    cible = construire(profil, recherches)
    etalonner(cible, list(signaux.values()), corpus)
    poids = reglages().scoring.poids
    return {o.id: calculer(profil, o, signaux[o.id], poids, cible, corpus).score for o in offres}


def metriques(scores: dict[int, float]) -> tuple[dict, list[int]]:
    ids = [i for i in ETIQUETTES if i in scores]
    paires = concordantes = 0.0
    for a in ids:
        for b in ids:
            if ETIQUETTES[a] > ETIQUETTES[b]:
                paires += 1
                concordantes += 1 if scores[a] > scores[b] else 0.5 if scores[a] == scores[b] else 0
    classement = sorted(ids, key=lambda i: -scores[i])
    ideal = sorted(ids, key=lambda i: -ETIQUETTES[i])

    def ndcg(k: int) -> float:
        gain = sum((2 ** ETIQUETTES[i] - 1) / math.log2(r + 2) for r, i in enumerate(classement[:k]))
        maxi = sum((2 ** ETIQUETTES[i] - 1) / math.log2(r + 2) for r, i in enumerate(ideal[:k]))
        return gain / maxi

    moyennes = {}
    for niveau in (3, 2, 1, 0):
        notes = [scores[i] for i in ids if ETIQUETTES[i] == niveau]
        moyennes[niveau] = round(sum(notes) / len(notes), 1) if notes else None
    return {
        "offres étiquetées": len(ids),
        "concordance": round(concordantes / paires, 3) if paires else None,
        "ndcg@20": round(ndcg(20), 3),
        "ndcg@50": round(ndcg(50), 3),
        "top 20 pertinentes (>=2)": sum(ETIQUETTES[i] >= 2 for i in classement[:20]),
        "top 20 hors sujet (0)": sum(ETIQUETTES[i] == 0 for i in classement[:20]),
        "moyenne par niveau 3/2/1/0": moyennes,
    }, classement


if __name__ == "__main__":
    profil, offres, recherches = charger()
    scores = scorer(profil, offres, recherches)
    resultats, classement = metriques(scores)
    for cle, valeur in resultats.items():
        print(f"{cle:<28} {valeur}")
    if "--detail" in sys.argv:
        titres = {o.id: o.titre for o in offres}
        for i in classement[:25]:
            print(f"  {scores[i]:5.1f}  [{ETIQUETTES[i]}]  {titres[i][:70]}")
