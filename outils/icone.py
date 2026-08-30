"""Génère `outils/dreamjob.ico`, l'icône du raccourci de bureau.

Écrite en Python pur, sans Pillow : installer une bibliothèque d'imagerie pour
dessiner quatre disques serait disproportionné, et l'environnement doit rester
léger. Le format ICO est un simple en-tête suivi de bitmaps BGRA.

Le dessin : une cible sur fond bleu nuit — trouver le bon poste, pas tous les
postes. Lisible à 16 pixels, ce qui exclut tout texte.

    cd backend; .\\.venv\\Scripts\\python.exe ..\\outils\\icone.py
"""

from __future__ import annotations

import struct
from pathlib import Path

TAILLES = (16, 32, 48, 64, 128, 256)

FOND = (0x1E, 0x29, 0x3B)        # bleu nuit
ANNEAU = (0xF5, 0xF7, 0xFA)      # blanc cassé
CENTRE = (0xE0, 0x7A, 0x3C)      # ambre

# Rayons en proportion du côté, du plus grand au plus petit.
COURONNES = (
    (0.40, ANNEAU),
    (0.30, FOND),
    (0.21, ANNEAU),
    (0.11, FOND),
    (0.055, CENTRE),
)

# Rayon d'arrondi du carré de fond, en proportion du côté.
ARRONDI = 0.22


def _dans_le_carre_arrondi(x: float, y: float, cote: float) -> bool:
    """Un carré aux coins arrondis, décrit par ses quatre disques de coin."""
    marge = cote * 0.04
    rayon = cote * ARRONDI
    gauche, haut = marge, marge
    droite, bas = cote - marge, cote - marge
    if not (gauche <= x <= droite and haut <= y <= bas):
        return False
    # Hors des coins, c'est un rectangle plein.
    cx = min(max(x, gauche + rayon), droite - rayon)
    cy = min(max(y, haut + rayon), bas - rayon)
    return (x - cx) ** 2 + (y - cy) ** 2 <= rayon ** 2


def _pixel(x: int, y: int, cote: int) -> tuple[int, int, int, int]:
    """Couleur BGRA d'un pixel, avec un lissage par sur-échantillonnage 3×3.

    Sans ce lissage, les cercles sont crénelés dès 32 pixels — l'icône a l'air
    bricolée, ce qu'elle est, mais autant que ça ne se voie pas.
    """
    sous = 3
    accumule = [0, 0, 0, 0]
    for sy in range(sous):
        for sx in range(sous):
            px = x + (sx + 0.5) / sous
            py = y + (sy + 0.5) / sous
            if not _dans_le_carre_arrondi(px, py, cote):
                continue
            distance = ((px - cote / 2) ** 2 + (py - cote / 2) ** 2) ** 0.5
            couleur = FOND
            for proportion, teinte in COURONNES:
                if distance <= cote * proportion:
                    couleur = teinte
            accumule[0] += couleur[2]      # B
            accumule[1] += couleur[1]      # G
            accumule[2] += couleur[0]      # R
            accumule[3] += 255
    total = sous * sous
    return tuple(c // total for c in accumule)  # type: ignore[return-value]


def _image(cote: int) -> bytes:
    """Un DIB 32 bits : en-tête, pixels BGRA de bas en haut, puis masque vide."""
    entete = struct.pack(
        "<IiiHHIIiiII",
        40,          # taille de l'en-tête
        cote,
        cote * 2,    # hauteur doublée : image + masque, comme l'exige le format
        1, 32, 0,    # plans, bits par pixel, compression
        cote * cote * 4,
        0, 0, 0, 0,
    )
    pixels = bytearray()
    for y in range(cote - 1, -1, -1):        # les DIB se lisent de bas en haut
        for x in range(cote):
            pixels += bytes(_pixel(x, y, cote))

    # Masque AND : inutile en 32 bits, mais sa place doit être réservée.
    octets_par_ligne = ((cote + 31) // 32) * 4
    masque = bytes(octets_par_ligne * cote)
    return entete + bytes(pixels) + masque


def ecrire(destination: Path) -> Path:
    images = [(cote, _image(cote)) for cote in TAILLES]

    entete = struct.pack("<HHH", 0, 1, len(images))
    decalage = len(entete) + 16 * len(images)
    entrees, corps = b"", b""
    for cote, donnees in images:
        entrees += struct.pack(
            "<BBBBHHII",
            cote if cote < 256 else 0,    # 256 se note 0, le champ tient sur un octet
            cote if cote < 256 else 0,
            0, 0, 1, 32,
            len(donnees), decalage,
        )
        corps += donnees
        decalage += len(donnees)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(entete + entrees + corps)
    return destination


if __name__ == "__main__":
    chemin = ecrire(Path(__file__).resolve().parent / "dreamjob.ico")
    print(f"{chemin} — {chemin.stat().st_size} octets, {len(TAILLES)} tailles")
