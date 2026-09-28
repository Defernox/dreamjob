"""La liste des employeurs suivis : `employeurs.yaml`, à la racine du projet.

Chaque employeur dit son logiciel de recrutement et l'adresse de son site
carrières. Ceux qu'on ne peut pas suivre y restent, avec le motif : c'est la
trace qui justifie la décision, comme pour les sources refusées de
`config.yaml`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger("dreamjob.employeurs")

ACTIF = "actif"


@dataclass
class Employeur:
    nom: str
    logiciel: str = ""
    adresse: str = ""
    categorie: str = ""
    statut: str = ACTIF
    motif: str = ""
    options: dict = field(default_factory=dict)


def charger(chemin: Path) -> list[Employeur]:
    """Tous les employeurs du fichier, actifs ou non. Un fichier absent ou
    illisible rend une liste vide : la source se tait, le scan continue."""
    if not chemin.exists():
        log.warning("Liste des employeurs introuvable : %s", chemin)
        return []
    try:
        donnees = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        log.error("Liste des employeurs illisible (%s) : %s", chemin, e)
        return []
    employeurs = []
    for categorie, liste in (donnees.get("employeurs") or {}).items():
        for entree in liste or []:
            if not isinstance(entree, dict) or not entree.get("nom"):
                continue
            connus = {"nom", "logiciel", "adresse", "statut", "motif"}
            employeurs.append(Employeur(
                nom=str(entree["nom"]),
                logiciel=str(entree.get("logiciel") or ""),
                adresse=str(entree.get("adresse") or ""),
                categorie=categorie,
                statut=str(entree.get("statut") or ACTIF),
                motif=str(entree.get("motif") or ""),
                options={k: v for k, v in entree.items() if k not in connus},
            ))
    return employeurs
