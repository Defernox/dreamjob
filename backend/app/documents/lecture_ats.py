"""Ce qu'un logiciel de recrutement lira du CV qui vient d'être produit.

Le panneau « Ce que verra le recruteur » (`correspondance.py`) juge le *profil*,
avant de générer, et compte les synonymes. Un ATS, lui, ne voit ni le profil ni
les synonymes : il convertit **le fichier** en texte, puis un recruteur y
cherche des mots. Ce module refait ces deux gestes sur le document réel.

1. **La structure du Word.** Tableaux, zones de texte, colonnes, images, en-tête
   et pied de page sont ce qu'un analyseur perd ou lit dans le désordre. Le
   modèle actuel n'en contient pas — mais c'est un fichier que l'utilisateur
   remplace à sa guise (`templates/cv_modele.docx`) : le jour où il y met une
   colonne latérale, le dossier le dit.
2. **Le texte extrait du PDF**, tel qu'un analyseur l'obtient : non vide, le nom
   en tête, l'e-mail et le téléphone dans le corps, les rubriques classiques
   reconnues.
3. **Les mots de l'annonce, au mot près.** Pour chaque terme sur lequel
   l'annonce insiste : écrit tel quel dans le CV, sous une forme voisine
   (pluriel, féminin), **dit autrement** (un synonyme que le score reconnaît,
   mais qu'une recherche par mot-clé ne trouvera pas), ou absent. « Dit
   autrement » est la seule liste sur laquelle on puisse agir sans mentir :
   le candidat l'a, il ne le dit pas avec les mots du recruteur.

Pur code, aucun appel. Rien n'est corrigé ici : la lecture se consigne dans
`generation.json`, et seuls les vrais défauts du document deviennent des
avertissements.
"""

from __future__ import annotations

import logging
import re
import zipfile
from pathlib import Path

from ..models import Offer, Profile
from ..scoring.couverture import MAX_TERMES, _termes_recurrents
from ..scoring.lexique import racine
from ..scoring.score import presence
from ..scoring.texte import mots, normaliser
from .intitule import nettoyer_intitule

log = logging.getLogger("dreamjob.lecture_ats")

# Une rubrique que tout analyseur reconnaît, et les titres qui la désignent.
RUBRIQUES = {
    "expériences": ("experience", "experiences", "experiences professionnelles",
                    "experience professionnelle", "parcours professionnel",
                    "work experience", "professional experience", "employment history"),
    "formation": ("formation", "formations", "education", "diplomes", "etudes"),
    "compétences": ("competences", "skills", "competences cles", "savoir-faire"),
}
LONGUEUR_TITRE = 40
# En deçà, le PDF est une image ou un fichier vide : rien à lire.
TEXTE_MINIMAL = 200

_EMAIL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


# --- 1. La structure du Word --------------------------------------------------

def defauts_de_structure(docx: Path) -> list[str]:
    """Ce qui, dans le fichier Word, se lit mal ou pas du tout par un analyseur."""
    try:
        with zipfile.ZipFile(docx) as archive:
            corps = archive.read("word/document.xml").decode("utf-8", "replace")
            marges = [archive.read(n).decode("utf-8", "replace") for n in archive.namelist()
                      if re.fullmatch(r"word/(header|footer)\d*\.xml", n)]
    except (OSError, KeyError, zipfile.BadZipFile):
        return []
    defauts = []
    if "<w:tbl>" in corps or "<w:tbl " in corps:
        defauts.append("le CV range du texte dans un tableau : un ATS peut le lire ligne par "
                       "ligne, dans le désordre")
    if "w:txbxContent" in corps:
        defauts.append("le CV contient une zone de texte : les analyseurs l'ignorent souvent")
    if re.search(r'<w:cols\b[^>]*w:num="(?:[2-9]|\d{2,})"', corps):
        defauts.append("le CV est en colonnes : un ATS lit en travers, d'une colonne à l'autre")
    if "<w:drawing>" in corps or "<w:pict>" in corps:
        defauts.append("le CV contient une image (photo, logo, icône) : elle n'est pas lue, et "
                       "un texte placé dedans est perdu")
    if any(re.sub(r"<[^>]+>", "", marge).strip() for marge in marges):
        defauts.append("le CV écrit dans l'en-tête ou le pied de page : cette zone est souvent "
                       "ignorée — les coordonnées doivent être dans le corps")
    return defauts


# --- 2. Le texte qu'un analyseur obtient --------------------------------------

def texte_du_pdf(pdf: Path) -> str:
    try:
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf)).pages)
    except Exception as e:  # noqa: BLE001 — un PDF illisible est justement ce qu'on signale
        log.warning("PDF illisible pour la lecture ATS (%s).", type(e).__name__)
        return ""


def texte_du_docx(docx: Path) -> str:
    """Les paragraphes du corps, dans l'ordre du fichier — sans les tableaux ni
    les zones de texte, comme un analyseur prudent."""
    try:
        from docx import Document
        return "\n".join(p.text for p in Document(str(docx)).paragraphs)
    except Exception as e:  # noqa: BLE001
        log.warning("Word illisible pour la lecture ATS (%s).", type(e).__name__)
        return ""


def _chiffres(texte: str) -> str:
    return re.sub(r"\D", "", texte or "")


def _rubriques_reconnues(texte: str) -> list[str]:
    titres = {normaliser(ligne) for ligne in texte.split("\n") if len(ligne.strip()) <= LONGUEUR_TITRE}
    return [nom for nom, variantes in RUBRIQUES.items() if titres & set(variantes)]


# --- 3. Les mots de l'annonce, au mot près ------------------------------------

def mots_de_l_annonce(texte_cv: str, offre: Offer) -> dict[str, list[str]]:
    """Les termes récurrents de l'annonce, rangés selon ce que le CV en dit."""
    presents = set(mots(texte_cv))
    racines = {racine(m) for m in presents}
    rangement: dict[str, list[str]] = {"au_mot_pres": [], "forme_voisine": [],
                                       "dit_autrement": [], "absents": []}
    for _, terme in _termes_recurrents(offre)[:MAX_TERMES]:
        if terme in presents:
            rangement["au_mot_pres"].append(terme)
        elif racine(terme) in racines:
            rangement["forme_voisine"].append(terme)
        elif presence(terme, presents, flou=True) > 0.0:
            rangement["dit_autrement"].append(terme)
        else:
            rangement["absents"].append(terme)
    return rangement


# --- Synthèse ----------------------------------------------------------------

def lire(cv_docx: Path | None, cv_pdf: Path | None, profil: Profile, offre: Offer) -> dict:
    """La lecture du CV produit, et les avertissements qu'elle justifie."""
    structure = defauts_de_structure(cv_docx) if cv_docx else []
    depuis_pdf = bool(cv_pdf)
    texte = texte_du_pdf(cv_pdf) if cv_pdf else (texte_du_docx(cv_docx) if cv_docx else "")
    lisible = len(texte.strip()) >= TEXTE_MINIMAL

    avertissements = [f"Lecture ATS — {defaut}." for defaut in structure]
    if not lisible:
        if depuis_pdf:
            avertissements.append("Lecture ATS — le PDF du CV ne contient pas de texte lisible : "
                                  "un ATS n'y trouvera rien. Envoyez le Word.")
        return {"lisible": False, "structure": structure, "avertissements": avertissements}

    nu = normaliser(texte)
    lignes = [l.strip() for l in texte.split("\n") if l.strip()]
    nom = normaliser(f"{profil.prenom} {profil.nom}")
    coordonnees = {
        "nom_en_tete": bool(nom) and nom in normaliser(" ".join(lignes[:3])),
        "email": bool(profil.email) and profil.email.strip().lower() in texte.lower(),
        "telephone": bool(_chiffres(profil.telephone)) and _chiffres(profil.telephone) in _chiffres(texte),
    }
    if profil.email and not coordonnees["email"]:
        trouve = _EMAIL.search(texte)
        avertissements.append(
            "Lecture ATS — votre e-mail n'est pas lu tel quel dans le CV"
            + (f" (lu : {trouve.group()})." if trouve else " : un recruteur ne pourra pas vous écrire."))
    if profil.telephone and not coordonnees["telephone"]:
        avertissements.append("Lecture ATS — votre téléphone n'est pas lu dans le CV.")
    if nom and not coordonnees["nom_en_tete"]:
        avertissements.append("Lecture ATS — votre nom n'ouvre pas le CV : un analyseur prend "
                              "souvent les premiers mots pour le nom du candidat.")

    rubriques = _rubriques_reconnues(texte)
    manquantes = [r for r in RUBRIQUES if r not in rubriques]
    if manquantes:
        avertissements.append(
            "Lecture ATS — rubrique non reconnue : " + ", ".join(manquantes) + ". Un titre "
            "classique (« Expériences professionnelles », « Formation », « Compétences ») "
            "range le contenu dans le bon champ.")

    intitule = normaliser(nettoyer_intitule(offre.titre, offre.lieu))
    termes = mots_de_l_annonce(texte, offre)
    total = sum(len(liste) for liste in termes.values())
    trouves = len(termes["au_mot_pres"]) + len(termes["forme_voisine"])
    return {
        "lisible": True,
        "source": "pdf" if depuis_pdf else "docx",
        "structure": structure,
        "coordonnees": coordonnees,
        "rubriques": rubriques,
        # L'intitulé exact de l'offre, tel qu'un recruteur le tape dans sa recherche.
        "intitule_exact": bool(intitule) and intitule in nu,
        "termes": termes,
        "termes_total": total,
        "termes_trouves": trouves,
        "taux_litteral": round(100 * trouves / total) if total else None,
        "avertissements": avertissements,
    }


def resume(lecture: dict) -> str:
    """Une ligne pour l'utilisateur. Vide si la lecture n'a pas pu se faire."""
    if not lecture or not lecture.get("lisible"):
        return ""
    coordonnees = lecture.get("coordonnees") or {}
    morceaux = [
        "intitulé de l'offre " + ("✓" if lecture.get("intitule_exact") else "✗"),
        "coordonnées " + ("✓" if coordonnees.get("email") and coordonnees.get("telephone") else "✗"),
    ]
    if lecture.get("termes_total"):
        morceaux.append(f"{lecture['termes_trouves']} mots-clés de l'annonce sur "
                        f"{lecture['termes_total']} au mot près")
    return "Lu par un ATS : " + " · ".join(morceaux)
