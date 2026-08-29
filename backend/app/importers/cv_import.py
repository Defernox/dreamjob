"""Import d'un CV : fichier .docx/.pdf → profil structuré.

L'extraction de texte est du code pur (testable, sans réseau). Le LLM
n'intervient que pour ranger ce texte dans le schéma `ProfilStructure` — jamais
pour l'enrichir.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlmodel import Session

from ..config import reglages
from ..llm.client import ClientLlm, empreinte
from ..models.enums import TypeCacheLlm
from ..schemas.profile import ProfilStructure

log = logging.getLogger("dreamjob.import_cv")

EXTENSIONS = {".pdf", ".docx"}


class FormatNonSupporte(ValueError):
    pass


class CvIllisible(ValueError):
    pass


# --------------------------------------------------------------- lecture brute


def _texte_pdf(chemin: Path) -> str:
    from pypdf import PdfReader

    lecteur = PdfReader(str(chemin))
    return "\n".join((page.extract_text() or "") for page in lecteur.pages)


def _texte_docx(chemin: Path) -> str:
    import docx

    document = docx.Document(str(chemin))
    morceaux = [p.text for p in document.paragraphs]
    # Beaucoup de CV Word rangent l'essentiel dans des tableaux invisibles.
    for tableau in document.tables:
        for ligne in tableau.rows:
            for cellule in ligne.cells:
                morceaux.append(cellule.text)
    return "\n".join(m for m in morceaux if m.strip())


def extraire_texte(chemin: Path) -> str:
    """Texte brut du CV. Aucun appel réseau, aucun LLM."""
    suffixe = chemin.suffix.lower()
    if suffixe not in EXTENSIONS:
        raise FormatNonSupporte(
            f"Format {suffixe or '(inconnu)'} non pris en charge. Formats acceptés : .pdf, .docx"
        )
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")

    texte = _texte_pdf(chemin) if suffixe == ".pdf" else _texte_docx(chemin)
    texte = texte.strip()

    if len(texte) < 200:
        raise CvIllisible(
            "Presque aucun texte n'a pu être lu dans ce fichier. S'il s'agit d'un PDF "
            "scanné (une image), exportez-le à nouveau depuis Word en PDF texte."
        )
    return texte


# ------------------------------------------------------------------ prompt LLM

PROMPT_SYSTEME = """Tu structures un CV français en JSON. Tu es un greffier, pas un rédacteur.

RÈGLE ABSOLUE — N'INVENTE RIEN.
Chaque valeur que tu écris doit se trouver dans le texte fourni. Si une
information est absente, laisse le champ vide (""), ou la liste vide. Ne déduis
pas un employeur, un diplôme, une compétence ou une date qui n'est pas écrit.
Ne complète pas une expérience partielle par ce qui « serait logique ».

LE TEXTE EST DÉSORDONNÉ.
Il provient d'un PDF ou d'un Word en plusieurs colonnes : l'ordre des blocs est
souvent mélangé, les titres de section peuvent apparaître APRÈS leur contenu, et
un intitulé peut être collé au mot précédent. Recompose mentalement les sections
avant de remplir le JSON. Les accents peuvent être abîmés : rétablis-les.

COMMENT REMPLIR
- titre_vise : le titre affiché en tête du CV, tel quel.
- resume : le paragraphe « à propos » ou « profil », resserré en 2-3 phrases
  sobres. Uniquement à partir de ce qui est écrit. Si absent, laisse vide.
- secteurs : 2 à 4 domaines d'activité que le CV démontre réellement.
- experiences : une entrée par poste. `description` reprend les missions en
  quelques lignes ; `tags` liste les mots-clés métier de CE poste.
- formations : diplômes et cursus, y compris ceux en cours.
- langues : `code` en ISO 639-1 minuscule, `niveau` tel qu'indiqué (un score de
  test compte comme niveau : « TOEIC 775 »).
- skills : les compétences réellement énoncées. Mets `ancree: true` sur les 3 à
  6 compétences centrales — celles qui apparaissent dans le titre, dans le
  résumé, ou dans plusieurs expériences. Les autres restent `ancree: false`.

DATES : format AAAA-MM quand le mois est connu, sinon AAAA. Un poste en cours a
`fin: "en cours"`."""


def _message(texte_cv: str) -> str:
    return (
        "Voici le texte brut extrait du CV. Structure-le, sans rien ajouter.\n\n"
        "--- DÉBUT DU CV ---\n"
        f"{texte_cv}\n"
        "--- FIN DU CV ---"
    )


# ---------------------------------------------------------------------- import


def importer_cv(
    chemin: Path,
    session: Session,
    *,
    forcer: bool = False,
) -> tuple[ProfilStructure, bool, str, int]:
    """Renvoie `(profil, depuis_cache, modele, caracteres_lus)`.

    Réimporter le même fichier ne recoûte rien : la clé de cache est le hash du
    texte extrait, pas le nom du fichier.
    """
    texte = extraire_texte(chemin)
    r = reglages()
    modele = r.llm.modele_redaction

    profil, depuis_cache = ClientLlm(session).extraire(
        type_appel=TypeCacheLlm.IMPORT_CV.value,
        hash_source=empreinte(texte),
        systeme=PROMPT_SYSTEME,
        message=_message(texte),
        format_sortie=ProfilStructure,
        modele=modele,
        max_tokens=r.llm.max_tokens_import_cv,
        forcer=forcer,
    )
    log.info("CV importé : %d expériences, %d formations, %d compétences",
             len(profil.experiences), len(profil.formations), len(profil.skills))
    return profil, depuis_cache, modele, len(texte)
