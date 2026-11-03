"""Mesure la qualité du classement contre des étiquettes posées à la main.

    backend\\.venv\\Scripts\\python.exe outils\\evaluer_score.py                (depuis la racine)
    backend\\.venv\\Scripts\\python.exe outils\\evaluer_score.py --detail       (+ le top 25)
    backend\\.venv\\Scripts\\python.exe outils\\evaluer_score.py --base serveur.db --lot outils\\lots\\lot-2026-11-02.xlsx

Un réglage du score se MESURE, il ne se devine pas : c'est ainsi qu'a été
conçue la version 7 (voir CLAUDE.md, « Le score en détail »). Le script lit la
base en LECTURE SEULE, calcule le score de toutes les offres du propriétaire
avec le code du dépôt, et compare le classement aux étiquettes :

- **concordance** : la part des paires d'offres d'étiquettes différentes que le
  score range dans le bon ordre (0,5 = hasard) ;
- **NDCG@20 / @50** : la qualité du haut du classement, parmi les offres
  étiquetées ;
- le nombre d'offres pertinentes et hors sujet dans le top 20 ;
- la note moyenne par niveau d'étiquette — elle doit décroître.

Deux jeux d'étiquettes, deux rôles :

- **le jeu de réglage** (`etiquettes_score.py`, 182 offres) : celui sur lequel
  la v7 a été mise au point. Ses chiffres sont flatteurs par construction —
  chaque réglage gardé l'a été parce qu'il les faisait monter ;
- **les lots de contrôle** (`--lot`, tirés par `tirer_lot.py`) : jamais
  regardés pendant un réglage. Ce sont eux qui disent si le score tient sur la
  base telle qu'elle est. Un réglage qui fait monter le premier et baisser les
  seconds est un réglage sur mesure pour 182 offres, pas une amélioration.

`--seuils` dit, pour chaque note possible du vert, quelle part des offres cœur
de cible on attrape et combien d'offres marginales on fait entrer. Sur un lot de
contrôle, les chiffres sont pondérés par les poids du tirage : ils estiment la
base entière, pas l'échantillon (les tranches hautes y sont surreprésentées
exprès).

Les offres auxquelles le propriétaire a postulé sont des étiquettes gratuites :
leur note est affichée à part. Un score qui laisse en orange ce à quoi l'on
postule rate quelque chose.

Rien n'est écrit, nulle part.
"""

from __future__ import annotations

import argparse
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
SEUILS = (50, 55, 60, 65, 70, 75, 80, 85, 90)


def _date(valeur):
    return datetime.fromisoformat(valeur) if valeur else None


def _connexion(base: Path | None) -> sqlite3.Connection:
    chemin = Path(base) if base else reglages().chemins.db
    if not chemin.exists():
        sys.exit(f"Base introuvable : {chemin}")
    c = sqlite3.connect(f"file:{chemin.resolve().as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _tables(c: sqlite3.Connection) -> set[str]:
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _proprietaire(c: sqlite3.Connection) -> int | None:
    if "utilisateur" not in _tables(c):
        return None
    ligne = c.execute("SELECT id FROM utilisateur WHERE proprietaire = 1").fetchone()
    return ligne[0] if ligne else None


def charger(base: Path | None = None):
    """(profil, offres, recherches) du propriétaire. Sur une base à comptes,
    seules les offres de SON fil : celles des amis fausseraient le corpus."""
    c = _connexion(base)
    colonnes = {r[1] for r in c.execute("PRAGMA table_info(profile)")}
    proprio = _proprietaire(c)
    # Le propriétaire, sur une base à comptes ; le seul profil, sinon.
    if "utilisateur_id" in colonnes and proprio is not None:
        ligne = c.execute("SELECT * FROM profile WHERE utilisateur_id = ?", (proprio,)).fetchone()
        filtre = f" AND utilisateur_id = {int(proprio)}"
    else:
        ligne, filtre = c.execute("SELECT * FROM profile ORDER BY id").fetchone(), ""
    p = dict(ligne)
    for k in JSON_PROFIL:
        p[k] = json.loads(p[k] or "[]")
    profil = Profile(**{k: v for k, v in p.items() if k in Profile.model_fields
                        and k not in ("created_at", "updated_at", "cv_importe_le")})
    requete = f"SELECT {', '.join(CHAMPS_OFFRE)} FROM offer"
    if proprio is not None and "score_offre" in _tables(c):
        requete += f" WHERE id IN (SELECT offer_id FROM score_offre WHERE utilisateur_id = {int(proprio)})"
    offres = []
    for r in c.execute(requete):
        d = dict(r)
        d["raw"] = json.loads(d["raw"] or "{}")
        for k in ("date_publication", "date_recuperation", "derniere_vue_le"):
            d[k] = _date(d[k])
        offres.append(Offer(**d))
    recherches = [json.loads(r[0]) for r in c.execute(
        f"SELECT mots_cles FROM recherche WHERE active = 1{filtre}")]
    return profil, offres, recherches


def postulees(base: Path | None = None) -> list[int]:
    """Les offres auxquelles le propriétaire a postulé."""
    c = _connexion(base)
    if "application" not in _tables(c):
        return []
    colonnes = {r[1] for r in c.execute("PRAGMA table_info(application)")}
    proprio = _proprietaire(c)
    if "utilisateur_id" in colonnes and proprio is not None:
        lignes = c.execute("SELECT offer_id FROM application WHERE utilisateur_id = ?", (proprio,))
    else:
        lignes = c.execute("SELECT offer_id FROM application")
    return [r[0] for r in lignes]


def avis_telegram(base: Path | None = None) -> dict[int, int]:
    """{offre: 1 intéressant / 0 pas pour moi} : les appuis sous les alertes."""
    c = _connexion(base)
    if "score_offre" not in _tables(c):
        return {}
    if "avis" not in {r[1] for r in c.execute("PRAGMA table_info(score_offre)")}:
        return {}
    proprio = _proprietaire(c)
    return {r[0]: r[1] for r in c.execute(
        "SELECT offer_id, avis FROM score_offre WHERE avis IS NOT NULL AND utilisateur_id = ?", (proprio,))}


def scorer(profil, offres, recherches) -> dict[int, float]:
    signaux = {o.id: extraire(o) for o in offres}
    corpus = Corpus.depuis(signaux.values())
    cible = construire(profil, recherches)
    etalonner(cible, list(signaux.values()), corpus)
    poids = reglages().scoring.poids
    return {o.id: calculer(profil, o, signaux[o.id], poids, cible, corpus).score for o in offres}


def metriques(scores: dict[int, float], etiquettes: dict[int, int] | None = None) -> tuple[dict, list[int]]:
    etiquettes = ETIQUETTES if etiquettes is None else etiquettes
    ids = [i for i in etiquettes if i in scores]
    if not ids:
        return {"offres étiquetées": 0}, []
    paires = concordantes = 0.0
    for a in ids:
        for b in ids:
            if etiquettes[a] > etiquettes[b]:
                paires += 1
                concordantes += 1 if scores[a] > scores[b] else 0.5 if scores[a] == scores[b] else 0
    classement = sorted(ids, key=lambda i: -scores[i])
    ideal = sorted(ids, key=lambda i: -etiquettes[i])

    def ndcg(k: int) -> float | None:
        gain = sum((2 ** etiquettes[i] - 1) / math.log2(r + 2) for r, i in enumerate(classement[:k]))
        maxi = sum((2 ** etiquettes[i] - 1) / math.log2(r + 2) for r, i in enumerate(ideal[:k]))
        return round(gain / maxi, 3) if maxi else None

    moyennes = {}
    for niveau in (3, 2, 1, 0):
        notes = [scores[i] for i in ids if etiquettes[i] == niveau]
        moyennes[niveau] = round(sum(notes) / len(notes), 1) if notes else None
    return {
        "offres étiquetées": len(ids),
        "concordance": round(concordantes / paires, 3) if paires else None,
        "ndcg@20": ndcg(20),
        "ndcg@50": ndcg(50),
        "top 20 pertinentes (>=2)": sum(etiquettes[i] >= 2 for i in classement[:20]),
        "top 20 hors sujet (0)": sum(etiquettes[i] == 0 for i in classement[:20]),
        "moyenne par niveau 3/2/1/0": moyennes,
    }, classement


def seuils(scores: dict[int, float], etiquettes: dict[int, int],
           poids: dict[int, float] | None = None) -> list[dict]:
    """Pour chaque seuil du vert : la part des offres cœur de cible (3) et des
    offres pertinentes (>= 2) au-dessus, la part de pertinentes parmi ce qui est
    au-dessus, et le volume estimé d'offres au-dessus dans la base.

    Avec les poids du tirage, chaque offre compte pour toutes celles de sa
    strate : les chiffres valent pour la base, pas pour l'échantillon."""
    ids = [i for i in etiquettes if i in scores]
    w = {i: (poids or {}).get(i, 1.0) for i in ids}

    def somme(cond) -> float:
        return sum(w[i] for i in ids if cond(i))

    total_3, total_2 = somme(lambda i: etiquettes[i] == 3), somme(lambda i: etiquettes[i] >= 2)
    lignes = []
    for t in SEUILS:
        dessus = somme(lambda i: scores[i] >= t)
        lignes.append({
            "seuil": t,
            "rappel des 3": round(somme(lambda i: etiquettes[i] == 3 and scores[i] >= t) / total_3, 2)
            if total_3 else None,
            "rappel des >=2": round(somme(lambda i: etiquettes[i] >= 2 and scores[i] >= t) / total_2, 2)
            if total_2 else None,
            "part >=2 au-dessus": round(somme(lambda i: etiquettes[i] >= 2 and scores[i] >= t) / dessus, 2)
            if dessus else None,
            "marginales/hors sujet au-dessus": round(somme(lambda i: etiquettes[i] <= 1 and scores[i] >= t)),
            "volume au-dessus": round(dessus),
        })
    return lignes


def lire_lot(chemin: Path) -> tuple[dict[int, int], dict[int, float]]:
    """(étiquettes, poids) d'un lot rempli. Les en-têtes font foi, pas les
    positions : un fichier retouché à la main reste lisible. Une ligne sans
    étiquette, ou avec autre chose que 0 à 3, est ignorée."""
    from openpyxl import load_workbook

    classeur = load_workbook(chemin, read_only=True, data_only=True)
    lignes = list(classeur["Lot"].iter_rows(values_only=True))
    entetes = [str(v or "").strip().lower() for v in lignes[0]]
    col_id, col_etiquette = entetes.index("id"), entetes.index("étiquette")
    etiquettes: dict[int, int] = {}
    for ligne in lignes[1:]:
        ident, valeur = ligne[col_id], ligne[col_etiquette]
        if ident is None or valeur is None or str(valeur).strip() == "":
            continue
        try:
            niveau = int(float(str(valeur).strip().replace(",", ".")))
        except ValueError:
            continue
        if niveau in (0, 1, 2, 3):
            etiquettes[int(ident)] = niveau
    poids: dict[int, float] = {}
    if "_tirage" in classeur.sheetnames:
        tirage = list(classeur["_tirage"].iter_rows(values_only=True))
        entetes = [str(v or "").strip().lower() for v in tirage[0]]
        col_id, col_poids = entetes.index("id"), entetes.index("poids")
        for ligne in tirage[1:]:
            if ligne[col_id] is not None:
                poids[int(ligne[col_id])] = float(ligne[col_poids] or 1.0)
    return etiquettes, poids


def _afficher(titre: str, resultats: dict) -> None:
    print(f"\n== {titre}")
    for cle, valeur in resultats.items():
        print(f"{cle:<28} {valeur}")


def _afficher_seuils(titre: str, lignes: list[dict]) -> None:
    print(f"\n== {titre}")
    print("seuil  rappel 3  rappel >=2  part >=2 au-dessus  marginales au-dessus  volume au-dessus")
    for l in lignes:
        def f(v):
            return "  -" if v is None else f"{v:>4}"
        print(f"{l['seuil']:>5}  {f(l['rappel des 3']):>8}  {f(l['rappel des >=2']):>10}"
              f"  {f(l['part >=2 au-dessus']):>18}  {l['marginales/hors sujet au-dessus']:>20}"
              f"  {l['volume au-dessus']:>16}")


def main(arguments: list[str] | None = None) -> None:
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--base", type=Path, help="base à lire (par défaut celle de config.yaml)")
    parseur.add_argument("--lot", type=Path, action="append", default=[],
                         help="lot de contrôle rempli (répétable)")
    parseur.add_argument("--detail", action="store_true", help="affiche le top 25 du jeu de réglage")
    parseur.add_argument("--seuils", action="store_true", help="analyse du seuil du vert")
    args = parseur.parse_args(arguments)

    profil, offres, recherches = charger(args.base)
    scores = scorer(profil, offres, recherches)
    titres = {o.id: o.titre for o in offres}
    print(f"{len(offres)} offres notées.")

    resultats, classement = metriques(scores)
    _afficher("Jeu de réglage (etiquettes_score.py) — flatteur par construction", resultats)
    if args.detail:
        for i in classement[:25]:
            print(f"  {scores[i]:5.1f}  [{ETIQUETTES[i]}]  {titres[i][:70]}")

    controle: dict[int, int] = {}
    poids: dict[int, float] = {}
    for chemin in args.lot:
        etiquettes, p = lire_lot(chemin)
        recouvrement = set(etiquettes) & set(ETIQUETTES)
        if recouvrement:
            print(f"\n! {chemin.name} : {len(recouvrement)} offres déjà dans le jeu de réglage, écartées.")
        etiquettes = {i: n for i, n in etiquettes.items() if i not in ETIQUETTES}
        absentes = [i for i in etiquettes if i not in scores]
        if absentes:
            print(f"! {chemin.name} : {len(absentes)} offres absentes de cette base, ignorées.")
        controle.update(etiquettes)
        poids.update({i: p.get(i, 1.0) for i in etiquettes})
    if args.lot:
        resultats, _ = metriques(scores, controle)
        _afficher(f"Lots de contrôle ({len(args.lot)} fichier(s)) — ce qui compte", resultats)

    if args.seuils:
        if controle:
            _afficher_seuils("Seuil du vert, estimé sur la base (lots de contrôle, pondérés)",
                             seuils(scores, controle, poids))
        else:
            _afficher_seuils("Seuil du vert, sur le jeu de réglage (non pondéré : indicatif)",
                             seuils(scores, ETIQUETTES))

    donnes = {i: v for i, v in avis_telegram(args.base).items() if i in scores}
    if donnes:
        pour = [i for i, v in donnes.items() if v == 1]
        contre = [i for i, v in donnes.items() if v == 0]

        def moyenne(ids_):
            return f"{sum(scores[i] for i in ids_) / len(ids_):.0f}" if ids_ else "-"

        print(f"\n== Avis Telegram ({len(donnes)})")
        # Pas d'émoji ici : la console Windows (cp1252) ne sait pas les écrire.
        print(f"intéressant {len(pour)} (note moyenne {moyenne(pour)}) · pas pour moi {len(contre)}"
              f" (note moyenne {moyenne(contre)}) · part d'alertes utiles {len(pour) / len(donnes):.0%}")
        # Seules les vertes sonnent : ces avis jugent la précision du vert, pas
        # ce qu'il laisse passer. Les « pas pour moi » les mieux notés sont les
        # erreurs à comprendre en premier.
        for i in sorted(contre, key=lambda i: -scores[i])[:10]:
            print(f"  non {scores[i]:5.1f}  {titres[i][:70]}")

    ids = [i for i in postulees(args.base) if i in scores]
    if ids:
        notes = sorted(scores[i] for i in ids)
        mediane = notes[len(notes) // 2]
        print(f"\n== Offres auxquelles tu as postulé ({len(ids)})")
        print(f"note médiane {mediane:.0f} · vertes (>= 75) {sum(n >= 75 for n in notes)}"
              f" · orange {sum(50 <= n < 75 for n in notes)} · sous 50 {sum(n < 50 for n in notes)}")
        for i in sorted(ids, key=lambda i: scores[i])[:10]:
            if scores[i] < 75:
                print(f"  {scores[i]:5.1f}  {titres[i][:70]}")


if __name__ == "__main__":
    main()
