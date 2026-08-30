"""Le dossier de candidature : CV, lettre, offre archivée — Word et PDF.

Un dossier par candidature, daté et nommé lisiblement, prêt à envoyer.
L'offre y est archivée telle qu'elle a été récupérée : une annonce disparaît
souvent quelques semaines après la publication.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from ..models import Offer, Profile
from ..scoring.couverture import mots_cles_non_couverts
from . import pdf as pdf_outil
from .cv_render import rendre as rendre_cv

log = logging.getLogger("dreamjob.dossier")

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


@dataclass
class Resultat:
    dossier: Path
    fichiers: list[Path] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    lettre_essais: int = 0
    # Ce que l'offre réclame et que le profil ne couvre pas. Le signal le plus
    # utile du dossier : il ne juge pas l'offre, il dit ce qui manque.
    mots_cles_non_couverts: list[str] = field(default_factory=list)


def slug(texte: str, longueur: int = 60) -> str:
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFKD", texte or "") if not unicodedata.combining(c)
    )
    nettoye = re.sub(r"[^A-Za-z0-9]+", "-", sans_accents).strip("-").lower()
    return nettoye[:longueur].strip("-") or "offre"


# Windows plafonne un chemin complet à 260 caractères. Le dossier de
# candidature en consomme déjà une bonne part avant le nom des fichiers : on
# borne donc le nom, quitte à tronquer un intitulé à rallonge.
LONGUEUR_NOM_DOSSIER = 80


def nom_dossier(offre: Offer, jour: date | None = None) -> str:
    jour = jour or date.today()
    nom = f"{jour:%Y-%m-%d}-{slug(offre.entreprise, 32)}-{slug(offre.titre, 40)}"
    return nom.strip("-")[:LONGUEUR_NOM_DOSSIER].strip("-")


def date_en_lettres(jour: date) -> str:
    return f"{jour.day} {MOIS[jour.month - 1]} {jour.year}"


# ------------------------------------------------------------------- lettre


def ecrire_lettre(profil: Profile, offre: Offer, corps: str, destination: Path) -> Path:
    """Met le corps rédigé en page dans une lettre française classique."""
    document = docx.Document()
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    def paragraphe(texte: str, *, alignement=None, espace_apres: int = 6):
        p = document.add_paragraph(texte)
        if alignement is not None:
            p.alignment = alignement
        p.paragraph_format.space_after = Pt(espace_apres)
        return p

    # Expéditeur
    paragraphe(f"{profil.prenom} {profil.nom}".strip(), espace_apres=0)
    for ligne in filter(None, [
        ", ".join(filter(None, [profil.ville, profil.pays])),
        profil.telephone, profil.email,
    ]):
        paragraphe(ligne, espace_apres=0)

    # Destinataire
    paragraphe("", espace_apres=12)
    paragraphe(offre.entreprise or "Service recrutement", alignement=WD_ALIGN_PARAGRAPH.RIGHT,
               espace_apres=0)
    if offre.lieu:
        paragraphe(offre.lieu, alignement=WD_ALIGN_PARAGRAPH.RIGHT, espace_apres=0)

    paragraphe("", espace_apres=12)
    lieu = profil.ville or ""
    paragraphe(f"{lieu + ', ' if lieu else ''}le {date_en_lettres(date.today())}",
               alignement=WD_ALIGN_PARAGRAPH.RIGHT, espace_apres=18)

    objet = paragraphe(f"Objet : candidature au poste de {offre.titre}", espace_apres=18)
    objet.runs[0].bold = True

    paragraphe("Madame, Monsieur,", espace_apres=12)
    for bloc in [b.strip() for b in corps.split("\n\n") if b.strip()]:
        p = paragraphe(bloc, espace_apres=10)
        p.paragraph_format.first_line_indent = Pt(18)

    paragraphe("Je vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations "
               "distinguées.", espace_apres=18)
    paragraphe(f"{profil.prenom} {profil.nom}".strip(),
               alignement=WD_ALIGN_PARAGRAPH.RIGHT)

    destination.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(destination))
    return destination


# ------------------------------------------------------------------ dossier


def ouvrir(dossier: Path) -> bool:
    """Ouvre l'explorateur sur le dossier. Un échec n'est jamais bloquant."""
    try:
        if sys.platform == "win32":
            os.startfile(str(dossier))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", str(dossier)], check=False, timeout=10)
        else:
            subprocess.run(["xdg-open", str(dossier)], check=False, timeout=10)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Ouverture du dossier impossible : %s", e)
        return False


# Ce que cette fonction produit, et donc ce qu'elle a le droit d'effacer.
FICHIERS_PRODUITS = (
    "CV.docx", "CV.pdf",
    "Lettre_de_motivation.docx", "Lettre_de_motivation.pdf",
    "offre.json", "generation.json",
)


def _retirer_generation_precedente(dossier: Path) -> None:
    """Efface uniquement les fichiers que cette application génère.

    Tout autre document déposé là par l'utilisateur — notes, pièces jointes —
    est laissé intact.
    """
    for nom in FICHIERS_PRODUITS:
        chemin = dossier / nom
        try:
            chemin.unlink(missing_ok=True)
        except OSError as e:
            log.warning("Impossible de retirer %s : %s", nom, e)


def generer(
    profil: Profile,
    offre: Offer,
    racine: Path,
    modele_cv: Path,
    *,
    redacteur,
    tentatives_lettre: int = 3,
    relecture_lettre: bool = False,
    reordonner_cv: bool = True,
    ouvrir_apres: bool = True,
) -> Resultat:
    """Produit le dossier complet. Ce qui échoue est signalé, pas fatal.

    Un CV sans lettre reste utile ; un dossier vide ne l'est pas. Seule
    l'impossibilité de rendre le CV interrompt la génération.
    """
    from .lettre import rediger      # import tardif : évite un cycle

    dossier = racine / nom_dossier(offre)
    dossier.mkdir(parents=True, exist_ok=True)
    # Les documents de la génération précédente partent AVANT d'écrire les
    # nouveaux : sans cela, une lettre refusée par le garde-fou laissait en
    # place celle d'avant, décrivant un profil périmé, à côté d'un CV à jour.
    _retirer_generation_precedente(dossier)
    resultat = Resultat(dossier=dossier)

    # --- CV (obligatoire) ---
    cv = rendre_cv(profil, offre, modele_cv, dossier / "CV.docx", reordonner=reordonner_cv)
    resultat.fichiers.append(cv)

    # --- Lettre (le garde-fou peut légitimement refuser de livrer) ---
    lettre_docx: Path | None = None
    # Renseigné même en cas d'échec : quand une lettre manque, c'est le seul
    # endroit qui dit pourquoi.
    journal: dict = {"essais": 0, "refusee": None}
    try:
        corps, compte_rendu = rediger(profil, offre, redacteur,
                                      tentatives=tentatives_lettre,
                                      relecture=relecture_lettre)
        resultat.lettre_essais = compte_rendu["essais"]
        lettre_docx = ecrire_lettre(profil, offre, corps,
                                    dossier / "Lettre_de_motivation.docx")
        resultat.fichiers.append(lettre_docx)

        # Un défaut de style n'empêche pas de livrer — mais il se corrige en
        # dix secondes, à condition de savoir lequel chercher. On les nomme
        # tous, la disponibilité en tête : c'est une promesse au recruteur que
        # le profil ne fonde pas, et elle compte plus qu'un cliché.
        style = compte_rendu.get("style") or {}
        for cle, formulation in (
            ("disponibilite", "elle annonce une disponibilité absente de votre "
                              "profil : {}"),
            ("copies", "elle reprend des phrases de l'annonce : {}"),
            ("cliches", "elle contient des formules convenues : {}"),
            ("ouverture", "elle s'ouvre par une formule passe-partout : {}"),
            ("rythme", "son rythme est mécanique — {}"),
        ):
            if style.get(cle):
                resultat.avertissements.append(
                    "Lettre livrée, mais " + formulation.format(", ".join(style[cle]))
                )
        journal = {
            "essais": compte_rendu.get("essais"),
            "mots": compte_rendu.get("mots"),
            "relue": compte_rendu.get("relue"),
            "defauts_restants": {c: f for c, f in
                                 (compte_rendu.get("style") or {}).items() if f},
            "historique": [
                {"essai": h["essai"], "mots": h["mots"],
                 "bloquantes": {c: f for c, f in h["bloquantes"].items() if f},
                 "style": {c: f for c, f in h["style"].items() if f}}
                for h in compte_rendu.get("historique", [])
            ],
        }
    except Exception as e:  # noqa: BLE001 — une lettre manquante ne perd pas le CV
        log.warning("Lettre non générée : %s", e)
        resultat.avertissements.append(f"Lettre non générée — {e}")
        journal["refusee"] = str(e)

    # --- PDF ---
    for source in [cv] + ([lettre_docx] if lettre_docx else []):
        try:
            resultat.fichiers.append(pdf_outil.convertir(source))
        except Exception as e:  # noqa: BLE001 — sans LibreOffice, le Word suffit
            log.warning("PDF non généré pour %s : %s", source.name, e)
            resultat.avertissements.append(f"PDF non généré pour {source.name} — {e}")

    # --- Archive de l'offre : l'annonce disparaîtra ---
    archive = dossier / "offre.json"
    archive.write_text(json.dumps({
        "source": offre.source, "source_id": offre.source_id, "url": offre.url,
        "titre": offre.titre, "entreprise": offre.entreprise, "lieu": offre.lieu,
        "pays": offre.pays, "type_contrat": offre.type_contrat,
        "date_publication": offre.date_publication.isoformat() if offre.date_publication else None,
        "description_brute": offre.description_brute,
        "score": offre.score, "score_detail": offre.score_detail,
        "score_explication": offre.score_explication,
        "raw": offre.raw,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    resultat.fichiers.append(archive)

    # --- Ce qui manque au profil pour cette offre ---
    # Pur code, aucun appel : ce n'est pas un jugement sur l'offre mais sur le
    # profil. Répété sur vingt candidatures, il dessine ce qu'il faut combler.
    resultat.mots_cles_non_couverts = mots_cles_non_couverts(profil, offre)
    if resultat.mots_cles_non_couverts:
        resultat.avertissements.append(
            "L'offre insiste sur des termes que votre profil ne couvre pas : "
            + ", ".join(resultat.mots_cles_non_couverts[:6])
        )

    # --- Journal de génération ---
    # Quand une lettre est mauvaise, c'est le seul moyen de savoir quelle étape
    # a fauté : ce n'est pas du confort de développeur.
    journal_fichier = dossier / "generation.json"
    journal_fichier.write_text(json.dumps({
        "lettre": journal,
        "mots_cles_non_couverts": resultat.mots_cles_non_couverts,
        "cv_reordonne": reordonner_cv,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    resultat.fichiers.append(journal_fichier)

    if ouvrir_apres and not ouvrir(dossier):
        resultat.avertissements.append("Le dossier n'a pas pu être ouvert automatiquement.")

    log.info("Dossier généré : %s (%d fichiers)", dossier, len(resultat.fichiers))
    return resultat
