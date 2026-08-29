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


# --- Import en plusieurs passes ---------------------------------------------


def test_les_passes_couvrent_tout_le_profil():
    """Chaque champ de ProfilStructure doit être rempli par une passe, sinon il
    resterait silencieusement vide après un import."""
    from app.importers.cv_import import PASSES
    from app.schemas.profile import ProfilStructure

    couverts = set()
    for _, schema, _ in PASSES:
        couverts |= set(schema.model_fields)
    assert set(ProfilStructure.model_fields) == couverts


def test_chaque_passe_reste_courte():
    """Demander quatorze champs d'un coup fait dériver un modèle local : il
    range le nom dans le titre et oublie les compétences."""
    from app.importers.cv_import import PASSES

    for nom, schema, _ in PASSES:
        assert len(schema.model_fields) <= 9, f"la passe « {nom} » en demande trop"


def test_les_passes_ne_partagent_pas_la_meme_entree_de_cache(session, monkeypatch):
    """Sans variante, les quatre passes écraseraient la même ligne de cache et
    l'import ne conserverait que la dernière."""
    from app.importers import cv_import
    from app.llm.client import ClientLlm

    appels = []

    def faux_fournisseur(_self, systeme, message, format_sortie, modele, max_tokens):
        appels.append(format_sortie.__name__)
        return format_sortie()

    monkeypatch.setattr(ClientLlm, "_appeler_fournisseur", faux_fournisseur)
    monkeypatch.setattr(cv_import, "extraire_texte", lambda _: "Un CV. " * 60)

    _, du_cache, _, _ = cv_import.importer_cv(FIXTURES / "cv_exemple.docx", session)
    assert len(appels) == 4, "chaque passe doit appeler le modèle une fois"
    assert du_cache is False

    # Second import du même CV : tout doit sortir du cache.
    appels.clear()
    _, du_cache, _, _ = cv_import.importer_cv(FIXTURES / "cv_exemple.docx", session)
    assert appels == [], "les passes n'ont pas été mises en cache séparément"
    assert du_cache is True


def test_une_passe_deja_en_cache_n_est_pas_rejouee(session, monkeypatch):
    """Si une passe échoue, les autres restent acquises : réimporter ne refait
    que ce qui manque."""
    from app.importers import cv_import
    from app.llm.client import ClientLlm

    demandes = []

    def faux_fournisseur(_self, systeme, message, format_sortie, modele, max_tokens):
        demandes.append(format_sortie.__name__)
        if format_sortie.__name__ == "BlocIdentite":
            raise RuntimeError("panne du modèle")
        return format_sortie()

    monkeypatch.setattr(ClientLlm, "_appeler_fournisseur", faux_fournisseur)
    monkeypatch.setattr(cv_import, "extraire_texte", lambda _: "Un CV. " * 60)

    with pytest.raises(RuntimeError):
        cv_import.importer_cv(FIXTURES / "cv_exemple.docx", session)
    assert demandes == ["BlocIdentite"], "l'échec doit interrompre dès la première passe"
