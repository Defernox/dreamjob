"""Resserrer la mise en page d'un CV rendu, palier par palier, pour qu'il tienne
sur une page SANS couper de contenu.

Avant, un CV qui débordait perdait des puces d'expérience, alors que le modèle
gardait ses marges larges et ses espacements aérés : on sacrifiait le contenu à
la décoration. Désormais `dossier.py` essaie ces paliers dans l'ordre, chacun
cumulant les précédents, et ne retire des puces qu'au-delà du dernier.

| Palier | Ce qui change |
|---|---|
| 0 | le modèle tel quel |
| 1 | marges ramenées à 1,5 cm |
| 2 | espacements avant/après divisés par deux, interligne simple |
| 3 | toutes les tailles de police baissées de 0,5 pt |
| 4 | toutes les tailles de police baissées de 1 pt |

**Planchers, jamais franchis** : aucune police sous 10 pt, aucune marge sous
1,27 cm. Avec le modèle actuel (corps à 10,5 pt), le palier 4 ne réduit donc
plus que les titres : le corps s'arrête à 10 pt dès le palier 3.

**Les tailles sont lues là où le modèle les définit** : dans les styles
(`styles.xml`, valeurs par défaut comprises), directement sur les morceaux de
texte du corps (`document.xml`), et sur les puces (`numbering.xml`). Une taille
réduite sur le style mais pas sur le texte — ou l'inverse — ne changerait rien
au rendu : les trois sont réduites ensemble, titres compris. Une taille déjà
sous le plancher n'est jamais touchée, ni agrandie.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.shared import Cm

PLANCHER_POLICE_DEMI_POINTS = 20       # 10 pt : w:sz s'écrit en demi-points
PLANCHER_MARGE = Cm(1.27)
MARGE_RESSERREE = Cm(1.5)
INTERLIGNE_SIMPLE = 240                # w:line en 240e de ligne, règle « auto »


@dataclass(frozen=True)
class Palier:
    numero: int
    libelle: str
    marges: bool = False
    espacements: bool = False
    # Baisse de toutes les tailles de police, en demi-points.
    police: int = 0


PALIERS = (
    Palier(0, "modèle tel quel"),
    Palier(1, "marges à 1,5 cm", marges=True),
    Palier(2, "espacements divisés par deux, interligne simple", marges=True, espacements=True),
    Palier(3, "polices baissées de 0,5 pt", marges=True, espacements=True, police=1),
    Palier(4, "polices baissées de 1 pt", marges=True, espacements=True, police=2),
)
DERNIER_PALIER = PALIERS[-1]


def _parties(document) -> list:
    """Les éléments XML où vivent tailles et espacements."""
    elements = [document.element, document.styles.element]
    try:
        elements.append(document.part.numbering_part.element)
    except (KeyError, NotImplementedError, AttributeError):
        pass
    return elements


def _reduire_polices(document, demi_points: int) -> None:
    for racine in _parties(document):
        for balise in ("w:sz", "w:szCs"):
            for element in racine.iter(qn(balise)):
                brut = element.get(qn("w:val"))
                try:
                    taille = int(brut)
                except (TypeError, ValueError):
                    continue
                if taille <= PLANCHER_POLICE_DEMI_POINTS:
                    continue                      # déjà au plancher : on n'y touche pas
                element.set(qn("w:val"), str(max(PLANCHER_POLICE_DEMI_POINTS, taille - demi_points)))


def _resserrer_espacements(document) -> None:
    for racine in _parties(document):
        for element in racine.iter(qn("w:spacing")):
            # Dans un rPr, w:spacing est l'écart entre lettres, pas entre paragraphes.
            if element.getparent() is None or element.getparent().tag != qn("w:pPr"):
                continue
            for attribut in ("w:before", "w:after", "w:beforeLines", "w:afterLines"):
                brut = element.get(qn(attribut))
                if brut is not None and brut.lstrip("-").isdigit():
                    element.set(qn(attribut), str(int(brut) // 2))
            ligne, regle = element.get(qn("w:line")), element.get(qn("w:lineRule"))
            # Seul l'interligne proportionnel est ramené à simple : un interligne
            # exact ou minimal a été fixé pour une raison (une icône, une ligne
            # de séparation) et le réduire couperait le texte.
            if ligne and ligne.isdigit() and regle in (None, "auto") and int(ligne) > INTERLIGNE_SIMPLE:
                element.set(qn("w:line"), str(INTERLIGNE_SIMPLE))


def _resserrer_marges(document) -> None:
    for section in document.sections:
        for nom in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
            actuelle = getattr(section, nom)
            if actuelle is not None and actuelle > MARGE_RESSERREE:
                setattr(section, nom, max(MARGE_RESSERREE, PLANCHER_MARGE))


def appliquer(chemin: Path, palier: Palier) -> Path:
    """Applique `palier` au .docx, sur place. Le palier 0 ne touche à rien."""
    if palier.numero == 0:
        return chemin
    document = docx.Document(str(chemin))
    if palier.marges:
        _resserrer_marges(document)
    if palier.espacements:
        _resserrer_espacements(document)
    if palier.police:
        _reduire_polices(document, palier.police)
    document.save(str(chemin))
    return chemin
