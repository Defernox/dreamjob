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
from docx.shared import Cm, Pt

from ..models import Offer, Profile
from ..scoring.couverture import mots_cles_non_couverts
from . import pdf as pdf_outil
from .cv_render import PUCES_PAR_ESSAI
from .cv_render import rendre as rendre_cv
from .docx_outils import signer
from .intitule import au_poste, intitule_pour_cv, nettoyer_intitule

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
    # L'intitulé nettoyé : brut, le dossier s'appelait « …-financiers-h-f-paris-h ».
    intitule = nettoyer_intitule(offre.titre, offre.lieu) or offre.titre
    nom = f"{jour:%Y-%m-%d}-{slug(offre.entreprise, 32)}-{slug(intitule, 40)}"
    return nom.strip("-")[:LONGUEUR_NOM_DOSSIER].strip("-")


def date_en_lettres(jour: date) -> str:
    return f"{jour.day} {MOIS[jour.month - 1]} {jour.year}"


# ------------------------------------------------------------------- lettre


def ecrire_lettre(profil: Profile, offre: Offer, corps: str, destination: Path) -> Path:
    """Met le corps rédigé en page dans une lettre française classique."""
    document = docx.Document()
    # A4, pas US Letter. Le modèle par défaut de python-docx est au format
    # américain (21,6 × 27,9 cm) avec 3,2 cm de marges latérales : relevé sur la
    # première lettre rédigée par Opus — 305 mots, dont la signature seule
    # partait en page 2. Les lettres de mistral, plus courtes, passaient par
    # chance. Un recruteur français imprime en A4.
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.left_margin = section.right_margin = Cm(2.5)
    section.top_margin = section.bottom_margin = Cm(2.0)
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

    # L'intitulé nettoyé, et l'élision : « au poste de Analyste (H/F) » était la
    # première ligne lue par le recruteur dans environ une lettre sur dix.
    intitule = intitule_pour_cv(offre.titre, offre.lieu, profil.titre_vise, profil.accord)
    objet = paragraphe(f"Objet : candidature au poste {au_poste(intitule)}"
                       if intitule else "Objet : candidature", espace_apres=18)
    objet.runs[0].bold = True

    paragraphe("Madame, Monsieur,", espace_apres=12)
    for bloc in [b.strip() for b in corps.split("\n\n") if b.strip()]:
        p = paragraphe(bloc, espace_apres=10)
        p.paragraph_format.first_line_indent = Pt(18)

    paragraphe("Je vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations "
               "distinguées.", espace_apres=18)
    paragraphe(f"{profil.prenom} {profil.nom}".strip(),
               alignement=WD_ALIGN_PARAGRAPH.RIGHT)

    signer(document, profil, "Lettre de motivation", intitule)
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


def noms_de_fichiers(profil: Profile) -> tuple[str, str]:
    """(« CV_Maxime_Nicolas », « Lettre_de_motivation_Maxime_Nicolas »), sans
    extension.

    Ils s'appelaient « CV » et « Lettre_de_motivation » : le recruteur reçoit
    cinquante `CV.pdf` et doit renommer le vôtre pour le retrouver. Sans accents
    ni espaces : certains ATS abîment les noms de fichiers non ASCII au
    téléversement.
    """
    ascii_ = "".join(c for c in unicodedata.normalize("NFKD", f"{profil.prenom} {profil.nom}")
                     if not unicodedata.combining(c))
    nom = "_".join(re.findall(r"[A-Za-z0-9]+", ascii_))
    if not nom:
        return "CV", "Lettre_de_motivation"
    return f"CV_{nom}", f"Lettre_de_motivation_{nom}"


# Les noms qu'utilisaient les versions précédentes : un dossier régénéré doit
# les effacer aussi, sinon l'ancien `CV.pdf` reste à côté du nouveau.
ANCIENS_NOMS = ("CV.docx", "CV.pdf", "Lettre_de_motivation.docx", "Lettre_de_motivation.pdf")
JOURNAL = "generation.json"
ARCHIVE = "offre.json"


def _fichiers_produits(dossier: Path, profil: Profile) -> set[str]:
    """Ce que cette application a produit dans ce dossier, et a donc le droit
    d'effacer : les noms actuels, les anciens noms, et ceux que la génération
    précédente a consignés — le nom du candidat a pu changer entre-temps."""
    cv, lettre = noms_de_fichiers(profil)
    noms = {f"{b}.{ext}" for b in (cv, lettre) for ext in ("docx", "pdf")}
    noms |= set(ANCIENS_NOMS) | {JOURNAL, ARCHIVE}
    try:
        precedent = json.loads((dossier / JOURNAL).read_text(encoding="utf-8"))
        # Un nom consigné n'est accepté que s'il reste un simple nom de fichier :
        # le journal est un fichier du dossier, pas une source de chemins.
        noms |= {n for n in precedent.get("fichiers", [])
                 if isinstance(n, str) and n == Path(n).name}
    except (OSError, ValueError):
        pass
    return noms


def _retirer_generation_precedente(dossier: Path, profil: Profile) -> None:
    """Efface uniquement les fichiers que cette application génère.

    Tout autre document déposé là par l'utilisateur — notes, pièces jointes —
    est laissé intact.
    """
    for nom in _fichiers_produits(dossier, profil):
        chemin = dossier / nom
        try:
            chemin.unlink(missing_ok=True)
        except OSError as e:
            log.warning("Impossible de retirer %s : %s", nom, e)


def _cv_sur_une_page(profil: Profile, offre: Offer, modele: Path, dossier: Path,
                     reordonner: bool, ciblage=None) -> tuple[Path, Path | None, int]:
    """Rend le CV, puis vérifie sur le PDF qu'il tient sur une page.

    **On mesure, on ne devine pas.** Une version antérieure estimait la hauteur
    à partir du nombre de caractères : elle se trompait de huit lignes et
    rabotait les expériences à une seule puce pour un débordement imaginaire.
    La mise en page dépend de la police, des marges et des césures du modèle —
    seul le rendu la connaît.

    La première conversion serait de toute façon nécessaire : dans le cas
    courant, où le CV tient du premier coup, la mesure ne coûte rien.

    Sans LibreOffice, on ne peut pas mesurer : le CV part avec toutes ses
    puces, ce qui vaut mieux qu'un CV amputé au hasard.
    """
    cible = dossier / f"{noms_de_fichiers(profil)[0]}.docx"
    cv = pdf = None
    pages = 0

    for maximum in PUCES_PAR_ESSAI:
        cv = rendre_cv(profil, offre, modele, cible, reordonner=reordonner,
                       max_puces=maximum, ciblage=ciblage)
        try:
            pdf = pdf_outil.convertir(cv)
        except Exception as e:  # noqa: BLE001 — sans LibreOffice, le Word suffit
            log.warning("PDF non généré pour %s : %s", cv.name, e)
            return cv, None, 0

        pages = _nombre_de_pages(pdf)
        if pages <= 1:
            if maximum != PUCES_PAR_ESSAI[0]:
                log.info("CV ramené à une page avec %d puces par expérience.", maximum)
            return cv, pdf, pages

    return cv, pdf, pages


def _nombre_de_pages(pdf: Path) -> int:
    """Compte les pages sans dépendance : `/Type /Page` suffit dans un PDF
    produit par LibreOffice. Zéro si la lecture échoue — on ne rognera pas un
    CV sur une mesure qu'on n'a pas su faire."""
    try:
        brut = pdf.read_bytes()
    except OSError:
        return 0
    return len(re.findall(rb"/Type\s*/Page[^s]", brut))


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
    cibleur=None,
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
    _retirer_generation_precedente(dossier, profil)
    resultat = Resultat(dossier=dossier)

    # --- CV ciblé : calculé UNE fois, avant la boucle qui tient la page ---
    # Dans la boucle, il serait redemandé — et payé — à chaque essai de mise en
    # page. Un échec n'empêche rien : le CV part avec les puces du profil.
    ciblage = None
    if cibleur is not None:
        from .ciblage import cibler
        from .cv_render import puces_du_profil

        try:
            ciblage = cibler(profil, offre, puces_du_profil(profil), cibleur)
        except Exception as e:  # noqa: BLE001 — un CV non ciblé reste un CV
            log.warning("CV non ciblé : %s", e)
            resultat.avertissements.append(f"CV non adapté à l'offre — {e}")

    # --- CV (obligatoire), tenu sur une page ---
    cv, cv_pdf, pages = _cv_sur_une_page(profil, offre, modele_cv, dossier, reordonner_cv,
                                         ciblage)
    resultat.fichiers.append(cv)
    if cv_pdf is not None:
        resultat.fichiers.append(cv_pdf)
    if pages and pages > 1:
        resultat.avertissements.append(
            f"Le CV tient sur {pages} pages malgré la réduction des puces — "
            "raccourcissez les descriptions d'expériences dans l'onglet Profil."
        )

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
                                    dossier / f"{noms_de_fichiers(profil)[1]}.docx")
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
    for source in ([lettre_docx] if lettre_docx else []):
        try:
            pdf_lettre = pdf_outil.convertir(source)
            resultat.fichiers.append(pdf_lettre)
            # Mesuré, comme le CV : une lettre qui déborde perd sa signature
            # sur une seconde page que personne n'imprimera.
            pages_lettre = _nombre_de_pages(pdf_lettre)
            if pages_lettre > 1:
                resultat.avertissements.append(
                    f"La lettre tient sur {pages_lettre} pages : raccourcissez-la avant "
                    "de l'envoyer.")
        except Exception as e:  # noqa: BLE001 — sans LibreOffice, le Word suffit
            log.warning("PDF non généré pour %s : %s", source.name, e)
            resultat.avertissements.append(f"PDF non généré pour {source.name} — {e}")

    # --- Archive de l'offre : l'annonce disparaîtra ---
    archive = dossier / ARCHIVE
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
    consommation = (list(getattr(cibleur, "consommation", []))
                    + list(getattr(redacteur, "consommation", [])))
    journal_fichier = dossier / JOURNAL
    journal_fichier.write_text(json.dumps({
        # Consignés pour que la génération suivante sache quoi effacer, même si
        # le nom du candidat — donc celui des fichiers — a changé entre-temps.
        "fichiers": sorted({f.name for f in resultat.fichiers} | {JOURNAL}),
        "lettre": journal,
        "mots_cles_non_couverts": resultat.mots_cles_non_couverts,
        "cv_reordonne": reordonner_cv,
        "ciblage": ciblage.journal if ciblage else None,
        # Ce qu'a coûté ce dossier, appel par appel. L'utilisateur paie ses
        # générations : il doit pouvoir le lire sans ouvrir la console Anthropic.
        "consommation": consommation,
        "cout_usd": round(sum(c["usd"] for c in consommation), 4),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    resultat.fichiers.append(journal_fichier)

    if ouvrir_apres and not ouvrir(dossier):
        resultat.avertissements.append("Le dossier n'a pas pu être ouvert automatiquement.")

    log.info("Dossier généré : %s (%d fichiers)", dossier, len(resultat.fichiers))
    return resultat
