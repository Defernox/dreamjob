"""Lecture des CV : du code pur, aucun appel réseau.

C'est la moitié du travail d'import qui peut casser silencieusement — un CV mal
lu produit un profil vide sans erreur visible.
"""

import pytest

from app.importers.cv_import import (
    PROMPT_SYSTEME,
    CvIllisible,
    FormatNonSupporte,
    extraire_texte,
)

from .conftest import FIXTURES


def test_lecture_docx_recupere_aussi_les_tableaux():
    """Beaucoup de CV Word rangent les compétences dans un tableau invisible."""
    texte = extraire_texte(FIXTURES / "cv_exemple.docx")
    assert "Camille Dupont" in texte
    assert "Gestion de projet" in texte   # vient d'une cellule de tableau
    assert "Instagram" in texte


def test_lecture_pdf():
    texte = extraire_texte(FIXTURES / "cv_exemple.pdf")
    assert "Camille Dupont" in texte
    assert "Fabrique Lumiere" in texte


def test_docx_et_pdf_donnent_le_meme_contenu():
    """Le même CV dans les deux formats doit produire le même profil."""
    mots_docx = set(extraire_texte(FIXTURES / "cv_exemple.docx").split())
    mots_pdf = set(extraire_texte(FIXTURES / "cv_exemple.pdf").split())
    communs = mots_docx & mots_pdf
    assert len(communs) / len(mots_docx) > 0.9


def test_format_refuse(tmp_path):
    fichier = tmp_path / "cv.txt"
    fichier.write_text("Camille Dupont", encoding="utf-8")
    with pytest.raises(FormatNonSupporte, match=r"\.pdf, \.docx"):
        extraire_texte(fichier)


def test_fichier_absent(tmp_path):
    with pytest.raises(FileNotFoundError):
        extraire_texte(tmp_path / "fantome.pdf")


def test_pdf_scanne_donne_un_message_utile(tmp_path):
    """Un PDF sans couche texte (photo scannée) : il faut le dire, pas produire un profil vide."""
    import docx

    d = docx.Document()
    d.add_paragraph("trois mots seulement")
    presque_vide = tmp_path / "vide.docx"
    d.save(presque_vide)

    with pytest.raises(CvIllisible, match="scanné"):
        extraire_texte(presque_vide)


def test_le_prompt_interdit_explicitement_l_invention():
    """Garde-fou : cette consigne ne doit jamais disparaître du prompt."""
    assert "N'INVENTE RIEN" in PROMPT_SYSTEME
    assert "laisse le champ vide" in PROMPT_SYSTEME
