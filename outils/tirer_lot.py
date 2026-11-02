"""Tire un lot d'offres à étiqueter à la main : le jeu de contrôle du score.

    backend\\.venv\\Scripts\\python.exe outils\\tirer_lot.py --base serveur.db
    backend\\.venv\\Scripts\\python.exe outils\\tirer_lot.py --base serveur.db --taille 150 --graine 7

Le jeu de réglage (`etiquettes_score.py`) a servi à mettre la v7 au point : on
ne peut plus s'en servir pour la juger. Ce script tire des offres que personne
n'a encore regardées, dans la base telle qu'elle est (sites des employeurs
compris), et les range dans un classeur Excel à remplir — une colonne
« étiquette », de 0 à 3. `evaluer_score.py --lot` les relit.

Trois choix, chacun contre un biais :

- **le tirage est stratifié** par source et par tranche de score, avec autant
  d'offres par tranche que possible. Tiré au hasard simple, un lot serait fait
  aux trois quarts d'offres hors sujet notées 20, et ne dirait rien du haut du
  classement ni du seuil du vert ;
- **chaque offre porte son poids** (offres de sa strate dans la base / offres
  tirées dans la strate), dans une feuille cachée : les estimations de
  `--seuils` valent ainsi pour la base entière, malgré la surreprésentation
  voulue des tranches hautes ;
- **le classeur ne montre pas la note**, et les offres y sont mélangées :
  étiqueter en voyant « 92 » pousse à répondre 3.

Les offres déjà étiquetées (jeu de réglage, lots précédents de `outils/lots/`)
ne sont jamais retirées. La base est lue en lecture seule.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent
sys.path.insert(0, str(DOSSIER))

from etiquettes_score import ETIQUETTES  # noqa: E402
from evaluer_score import charger, lire_lot, scorer  # noqa: E402

# Bornes basses des tranches de score. Le haut est découpé plus finement : c'est
# là que se décident le seuil du vert et les alertes.
TRANCHES = (0, 25, 50, 65, 75, 90)
LONGUEUR_EXTRAIT = 900

GUIDE = """\
Une offre, une note de 0 à 3, selon TON intérêt réel pour le poste — pas selon
ce que DreamJob en pense (la note n'est pas affichée, exprès).

3  cœur de cible : un poste que tu veux et que tu peux obtenir (marchés, middle
   office, risques, crédit, trésorerie, gestion de portefeuille… junior à
   confirmé, dans une langue que tu parles).
2  proche : tu postulerais peut-être (contrôle de gestion, analyste financier,
   SI finance, corporate finance, banque ou assurance hors cible), ou c'est ta
   cible mais trop senior ou trop exigeante.
1  à la marge : tu ne postulerais pas sans raison particulière (comptabilité,
   RAF, finances publiques, conseiller commercial, encadrement confirmé).
0  hors sujet, ou inaccessible (langue que tu ne parles pas, direction).

Dans le doute entre deux notes, prends la plus basse. Si l'extrait ne suffit
pas, ouvre le lien. Laisse la case vide si tu ne peux vraiment pas juger : la
ligne sera ignorée. Ne touche pas aux colonnes « id » et « étiquette » (leur
nom), le reste peut être déplacé ou masqué.
"""


def tranche(score: float) -> int:
    return max(b for b in TRANCHES if score >= b)


def deja_etiquetees() -> set[int]:
    vus = set(ETIQUETTES)
    for lot in sorted((DOSSIER / "lots").glob("*.xlsx")):
        try:
            etiquettes, poids = lire_lot(lot)
            # Un lot tiré mais pas encore rempli réserve quand même ses offres.
            vus |= set(etiquettes) | set(poids)
        except Exception as e:  # un fichier abîmé ne doit pas bloquer le tirage
            print(f"! {lot.name} illisible ({e}), ignoré.")
    return vus


def repartir(effectifs: dict[str, int], quota: int) -> dict[str, int]:
    """Répartit `quota` entre des strates, proportionnellement à leur effectif,
    au moins une par strate non vide tant que le quota le permet (plus forts
    restes). Jamais plus que l'effectif."""
    strates = [s for s, n in effectifs.items() if n > 0]
    if not strates or quota <= 0:
        return {}
    total = sum(effectifs[s] for s in strates)
    parts = {s: min(effectifs[s], quota * effectifs[s] / total) for s in strates}
    alloc = {s: int(parts[s]) for s in strates}
    for s in sorted(strates, key=lambda s: -effectifs[s]):
        if sum(alloc.values()) >= quota:
            break
        if alloc[s] == 0:
            alloc[s] = 1
    reste = quota - sum(alloc.values())
    for s in sorted(strates, key=lambda s: -(parts[s] - int(parts[s]))):
        if reste <= 0:
            break
        if alloc[s] < effectifs[s]:
            alloc[s] += 1
            reste -= 1
    return {s: n for s, n in alloc.items() if n > 0}


def tirer(scores: dict[int, float], sources: dict[int, str], taille: int, graine: int,
          exclues: set[int]) -> list[tuple[int, float, str]]:
    """[(id, poids, strate)] : autant d'offres que possible par tranche de score,
    réparties entre les sources au prorata, puis mélangées."""
    hasard = random.Random(graine)
    strates: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for i, s in scores.items():
        if i not in exclues:
            strates[tranche(s)][sources[i]].append(i)
    tranches = sorted(strates)
    # À parts égales entre tranches, autant que leur effectif le permet : une
    # tranche trop petite rend son reliquat aux autres.
    restant, a_servir = taille, [t for t in tranches]
    quotas = {}
    while a_servir and restant > 0:
        part = max(1, restant // len(a_servir))
        for t in list(a_servir):
            dispo = sum(len(v) for v in strates[t].values()) - quotas.get(t, 0)
            pris = min(part, dispo, restant)
            quotas[t] = quotas.get(t, 0) + pris
            restant -= pris
            if pris < part or dispo - pris == 0:
                a_servir.remove(t)
            if restant <= 0:
                break
    lot = []
    for t, quota in quotas.items():
        for source, n in repartir({s: len(v) for s, v in strates[t].items()}, quota).items():
            population = sorted(strates[t][source])
            for i in hasard.sample(population, n):
                lot.append((i, round(len(population) / n, 3), f"{t}+ · {source}"))
    hasard.shuffle(lot)
    return lot


def _extrait(texte: str | None) -> str:
    texte = re.sub(r"<[^>]+>", " ", texte or "")
    texte = re.sub(r"\s+", " ", texte).strip()
    return texte if len(texte) <= LONGUEUR_EXTRAIT else texte[:LONGUEUR_EXTRAIT].rsplit(" ", 1)[0] + " …"


def ecrire(chemin: Path, lot: list[tuple[int, float, str]], offres: dict) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    classeur = Workbook()
    feuille = classeur.active
    feuille.title = "Lot"
    entetes = ("id", "étiquette", "intitulé", "entreprise", "lieu", "contrat", "source", "annonce (extrait)",
               "lien")
    feuille.append(entetes)
    for i, _, _ in lot:
        o = offres[i]
        feuille.append((o.id, None, o.titre, o.entreprise, o.lieu or o.pays, o.type_contrat, o.source,
                        _extrait(o.description_brute), o.url))
    gras = Font(bold=True)
    for cellule in feuille[1]:
        cellule.font = gras
    feuille.freeze_panes = "C2"
    largeurs = {"A": 8, "B": 10, "C": 45, "D": 24, "E": 20, "F": 10, "G": 14, "H": 90, "I": 30}
    for col, largeur in largeurs.items():
        feuille.column_dimensions[col].width = largeur
    jaune = PatternFill("solid", fgColor="FFF4C2")
    for ligne in feuille.iter_rows(min_row=2):
        ligne[1].fill = jaune
        for cellule in ligne:
            cellule.alignment = Alignment(wrap_text=True, vertical="top")
        if ligne[8].value:
            ligne[8].hyperlink = ligne[8].value
    validation = DataValidation(type="list", formula1='"0,1,2,3"', allow_blank=True,
                                showErrorMessage=True, errorTitle="Étiquette",
                                error="Une note de 0 à 3, ou vide.")
    feuille.add_data_validation(validation)
    validation.add(f"B2:B{len(lot) + 1}")

    guide = classeur.create_sheet("Guide")
    for ligne in GUIDE.splitlines():
        guide.append((ligne,))
    guide.column_dimensions["A"].width = 100

    tirage = classeur.create_sheet("_tirage")
    tirage.append(("id", "poids", "strate"))
    for ligne in lot:
        tirage.append(ligne)
    tirage.sheet_state = "hidden"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    classeur.save(chemin)


def main(arguments: list[str] | None = None) -> Path:
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--base", type=Path, help="base à lire (par défaut celle de config.yaml)")
    parseur.add_argument("--taille", type=int, default=120, help="nombre d'offres à tirer (120)")
    parseur.add_argument("--graine", type=int, default=None, help="pour un tirage reproductible")
    parseur.add_argument("--sortie", type=Path, help="classeur à écrire (outils/lots/lot-AAAA-MM-JJ.xlsx)")
    args = parseur.parse_args(arguments)

    sortie = args.sortie or DOSSIER / "lots" / f"lot-{date.today().isoformat()}.xlsx"
    if sortie.exists():
        sys.exit(f"{sortie} existe déjà : choisis un autre nom (--sortie), il est peut-être déjà rempli.")
    graine = args.graine if args.graine is not None else random.SystemRandom().randrange(10 ** 6)

    profil, offres, recherches = charger(args.base)
    scores = scorer(profil, offres, recherches)
    par_id = {o.id: o for o in offres}
    lot = tirer(scores, {o.id: o.source for o in offres}, args.taille, graine, deja_etiquetees())
    ecrire(sortie, lot, par_id)

    print(f"{len(lot)} offres tirées sur {len(offres)} (graine {graine}) -> {sortie}")
    compte: dict[str, int] = defaultdict(int)
    for _, _, strate in lot:
        compte[strate.split(" · ")[0]] += 1
    print("par tranche de score : " + ", ".join(f"{t} {n}" for t, n in sorted(compte.items(),
                                                                             key=lambda x: int(x[0][:-1]))))
    return sortie


if __name__ == "__main__":
    main()
