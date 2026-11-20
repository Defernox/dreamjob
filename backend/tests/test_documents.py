"""Rendu du CV et fabrication du dossier de candidature.

Exigence du projet : « La mise en page du modèle ne doit jamais être cassée. »
On vérifie donc que les styles du modèle survivent au rendu.
"""

import json
from pathlib import Path

import docx
import pytest

from app.documents.cv_render import ModeleIntrouvable, rendre
from app.documents.dossier import ecrire_lettre, generer, nom_dossier, slug
from app.models import Offer, Profile

MODELE = Path(__file__).resolve().parents[2] / "templates" / "cv_modele.docx"

pytestmark = pytest.mark.skipif(
    not MODELE.exists(), reason="templates/cv_modele.docx absent"
)


@pytest.fixture
def profil():
    return Profile(
        prenom="Maxime", nom="Nicolas", ville="Paris", pays="France",
        email="test@example.com", telephone="06 00 00 00 00",
        titre_vise="Analyste financier", resume="Parcours en finance de marché.",
        secteurs=["banque"], pays_acceptes=["France"], contrats_acceptes=["CDI"],
        langues=[{"code": "fr", "libelle": "Français", "niveau": "natif"}],
        skills=[{"nom": "Analyse financière", "ancree": True},
                {"nom": "Recouvrement de créances", "ancree": False},
                {"nom": "Excel", "ancree": False}],
        experiences=[
            {"entreprise": "Association Sport", "poste": "Trésorier", "debut": "2021-09",
             "fin": "2022-09", "description": "Tenue de la trésorerie. Budget annuel."},
            {"entreprise": "Crédit Mutuel", "poste": "Gestionnaire export",
             "debut": "2023-09", "fin": "2025-09",
             "description": "Recouvrement de créances export. Analyse financière des dossiers."},
        ],
        formations=[{"etablissement": "EM Normandie", "diplome": "Master 2 Finance",
                     "annee": "2020-2025", "details": "Marchés financiers."},
                    {"etablissement": "ESLSCA", "diplome": "MBA Trading", "annee": "2026"}],
    )


@pytest.fixture
def offre():
    return Offer(source="test", source_id="1", titre="Chargé de recouvrement de créances",
                 entreprise="Assureur Crédit", lieu="92 - Nanterre", pays="France",
                 type_contrat="CDI",
                 description_brute="Recouvrement de créances export et analyse financière.")


def _textes(chemin: Path) -> list[str]:
    return [p.text.strip() for p in docx.Document(str(chemin)).paragraphs if p.text.strip()]


# --- Rendu du CV ------------------------------------------------------------


def test_le_cv_contient_tout_le_profil(profil, offre, tmp_path):
    joint = " | ".join(_textes(rendre(profil, offre, MODELE, tmp_path / "CV.docx")))
    assert "MAXIME NICOLAS" in joint
    for experience in profil.experiences:
        assert experience["entreprise"] in joint
    for formation in profil.formations:
        assert formation["diplome"] in joint


def test_aucun_crochet_du_modele_ne_subsiste(profil, offre, tmp_path):
    """Les [placeholders] du modèle doivent tous avoir été remplacés."""
    for texte in _textes(rendre(profil, offre, MODELE, tmp_path / "CV.docx")):
        assert "[" not in texte, f"placeholder non remplacé : {texte[:60]}"


def test_la_mise_en_page_du_modele_survit(profil, offre, tmp_path):
    """Les styles du modèle SONT la mise en page : ils doivent rester."""
    document = docx.Document(str(rendre(profil, offre, MODELE, tmp_path / "CV.docx")))
    styles = {p.style.name for p in document.paragraphs if p.style is not None}
    assert "Heading 2" in styles, "les titres de section ont perdu leur style"
    assert "List Paragraph" in styles, "les puces ont perdu leur style"


@pytest.mark.parametrize("reordonner", [True, False])
def test_les_experiences_suivent_les_dates_meme_contre_la_pertinence(offre, tmp_path, reordonner):
    """La plus récente en tête, même quand la plus ancienne colle mieux à l'offre.

    Elles étaient triées par pertinence : un stage de 2021 passait devant un
    mandat 2021-2022, et un recruteur qui lit un CV de haut en bas y voit un
    trou qu'on cache. Le profil est construit à rebours exprès — l'expérience
    ancienne est la seule à parler de recouvrement — sinon le test passerait
    par coïncidence.
    """
    profil = Profile(
        prenom="M", nom="N", skills=[{"nom": "Excel"}],
        experiences=[
            {"entreprise": "Assureur", "poste": "Chargé de recouvrement", "debut": "Mai 2021",
             "fin": "Juillet 2021", "description": "Recouvrement de créances export."},
            {"entreprise": "Association", "poste": "Trésorier", "debut": "Septembre 2021",
             "fin": "Septembre 2022", "description": "Tenue du budget annuel."},
            {"entreprise": "Banque", "poste": "Gestionnaire", "debut": "2023-09",
             "fin": "en cours", "description": "Suivi de portefeuille."},
        ])
    textes = _textes(rendre(profil, offre, MODELE, tmp_path / "CV.docx", reordonner=reordonner))
    position = {t: i for i, t in enumerate(textes)}
    assert position["Gestionnaire"] < position["Trésorier"] < position["Chargé de recouvrement"]


def test_quand_le_cv_deborde_on_garde_les_puces_qui_parlent_a_l_offre(offre, tmp_path):
    """Couper les N premières puces gardait ce que le profil citait d'abord, pas
    ce qui compte pour CETTE annonce."""
    profil = Profile(
        prenom="M", nom="N", skills=[{"nom": "Excel"}],
        experiences=[{"entreprise": "Banque", "poste": "Gestionnaire", "debut": "2023",
                      "description": "Organisation des séminaires internes.\n"
                                     "Accueil des nouveaux arrivants.\n"
                                     "Recouvrement de créances export auprès des clients."}])
    textes = _textes(rendre(profil, offre, MODELE, tmp_path / "CV.docx", max_puces=1))
    joint = "\n".join(textes)
    assert "Recouvrement de créances export" in joint
    assert "séminaires" not in joint


def test_les_puces_restent_dans_leur_experience(profil, offre, tmp_path):
    """Bug corrigé : les puces d'un bloc migraient vers le bloc suivant."""
    document = docx.Document(str(rendre(profil, offre, MODELE, tmp_path / "CV.docx")))
    bloc, puces = None, {}
    for paragraphe in document.paragraphs:
        texte = paragraphe.text.strip()
        if not texte:
            continue
        if paragraphe.style is not None and paragraphe.style.name == "List Paragraph":
            puces.setdefault(bloc, []).append(texte)
        elif any(r.bold for r in paragraphe.runs if r.bold):
            bloc = texte

    assert any("créances export" in p for p in puces.get("Gestionnaire export", []))
    assert any("trésorerie" in p.lower() for p in puces.get("Trésorier", []))


def test_les_rubriques_sans_contenu_disparaissent(profil, offre, tmp_path):
    """Un CV ne doit pas afficher « Certifications » quand il n'y en a aucune."""
    textes = _textes(rendre(profil, offre, MODELE, tmp_path / "CV.docx"))
    assert "Certifications" not in textes
    assert "Projets" not in textes


def test_le_titre_du_cv_reprend_l_intitule_de_l_offre(profil, offre, tmp_path):
    """C'est ce que lisent les filtres automatiques des recruteurs."""
    assert offre.titre in _textes(rendre(profil, offre, MODELE, tmp_path / "CV.docx"))


def test_modele_absent_donne_un_message_utile(profil, offre, tmp_path):
    with pytest.raises(ModeleIntrouvable, match="Déposez votre CV"):
        rendre(profil, offre, tmp_path / "fantome.docx", tmp_path / "CV.docx")


# --- Dossier de candidature -------------------------------------------------


def _redacteur_honnete(systeme, message):
    return "Mon parcours au Crédit Mutuel me prépare à ce poste. " * 25


def test_nom_de_dossier_lisible_et_sans_accent(offre):
    nom = nom_dossier(offre)
    assert nom.startswith("20")
    assert "assureur-credit" in nom
    # Utilisable tel quel sur le disque : ni accent, ni espace, ni ponctuation.
    assert slug(nom, len(nom)) == nom


def test_un_intitule_a_rallonge_ne_produit_pas_un_chemin_trop_long(profil, tmp_path):
    """Windows refuse au-delà de 260 caractères de chemin complet."""
    offre = Offer(source="t", source_id="1",
                  entreprise="Groupe International de Services Financiers et Assurantiels",
                  titre="Chargé de recouvrement de créances export à l'international "
                        "pour la zone Europe Moyen-Orient Afrique (H/F)")
    nom = nom_dossier(offre)
    assert len(nom) <= 80
    assert not nom.endswith("-")


def test_le_dossier_complet_est_produit(profil, offre, tmp_path):
    resultat = generer(profil, offre, tmp_path, MODELE,
                       redacteur=_redacteur_honnete, ouvrir_apres=False)
    noms = {f.name for f in resultat.fichiers}
    assert "CV_Maxime_Nicolas.docx" in noms
    assert "Lettre_de_motivation_Maxime_Nicolas.docx" in noms
    assert "offre.json" in noms


def test_l_offre_est_archivee_telle_quelle(profil, offre, tmp_path):
    """L'annonce disparaîtra du site : il faut en garder une copie."""
    from app.models import ScoreOffre

    note = ScoreOffre(utilisateur_id=1, offer_id=1, score=82.4)
    resultat = generer(profil, offre, tmp_path, MODELE,
                       redacteur=_redacteur_honnete, ouvrir_apres=False, note=note)
    archive = json.loads((resultat.dossier / "offre.json").read_text(encoding="utf-8"))
    assert archive["titre"] == offre.titre
    assert archive["description_brute"] == offre.description_brute
    assert archive["score"] == 82.4


def test_une_lettre_refusee_ne_fait_pas_perdre_le_cv(profil, offre, tmp_path):
    """Un CV sans lettre reste utile ; un dossier vide ne l'est pas."""
    def menteur(systeme, message):
        return "J'ai dirigé le fonds Bridgewater pendant dix ans. " * 25

    resultat = generer(profil, offre, tmp_path, MODELE, redacteur=menteur,
                       tentatives_lettre=1, ouvrir_apres=False)
    noms = {f.name for f in resultat.fichiers}
    assert "CV_Maxime_Nicolas.docx" in noms
    assert "Lettre_de_motivation_Maxime_Nicolas.docx" not in noms
    assert any("Lettre non générée" in a for a in resultat.avertissements)


def test_la_lettre_est_mise_en_page_a_la_francaise(profil, offre, tmp_path):
    textes = _textes(ecrire_lettre(profil, offre, "Mon parcours.", tmp_path / "L.docx"))
    assert any(t.startswith("Objet : candidature") for t in textes)
    assert "Madame, Monsieur," in textes
    assert any("salutations distinguées" in t for t in textes)
    assert "Assureur Crédit" in textes


# --- Le classement du CV parle la même langue que le score ------------------


def test_le_classement_du_cv_reconnait_les_synonymes():
    """`_pertinence` était une troisième implémentation de l'appariement, sans
    les synonymes : une expérience « risques de crédit » ne rencontrait jamais
    une offre parlant de « credit risk »."""
    from app.documents.cv_render import _pertinence
    from app.scoring.texte import mots

    offre_en = set(mots("credit risk analysis for banking counterparties"))
    assert _pertinence("gestion des risques de crédit", offre_en) > 0.0


def test_le_classement_du_cv_pondere_les_mots_generiques():
    """Une expérience reconnue sur le seul mot « gestion » ne doit pas passer
    devant une expérience réellement pertinente."""
    from app.documents.cv_render import _pertinence
    from app.scoring.texte import mots

    offre = set(mots("gestion des stocks en entrepôt"))
    generique = _pertinence("gestion de trésorerie", offre)
    assert generique < 0.5


def test_le_cv_et_le_score_utilisent_la_meme_mesure():
    """Deux mesures différentes finiraient par se contredire sous les yeux de
    l'utilisateur : un CV qui met en avant ce que le score juge hors sujet."""
    from app.documents.cv_render import _pertinence
    from app.scoring.score import presence
    from app.scoring.texte import mots

    vocabulaire = set(mots("analyse financière et suivi des encours clients"))
    for terme in ("analyse financière", "gestion de trésorerie", "soudure à l'arc"):
        assert _pertinence(terme, vocabulaire) == presence(terme, vocabulaire, flou=False)


# --- Le CV tient sur une page ------------------------------------------------


def test_le_cv_ne_porte_aucune_ligne_de_mobilite(profil, offre, tmp_path):
    """Les pays acceptés servent à filtrer les offres, pas à figurer sur un CV :
    le recruteur sait où est son poste. Dix-sept pays s'étalaient sur trois
    lignes d'en-tête, sans rien apprendre à personne."""
    from app.documents.cv_render import rendre

    profil.pays_acceptes = [f"Pays{i}" for i in range(17)]
    textes = _textes(rendre(profil, offre, MODELE, tmp_path / "CV.docx"))
    assert not any("Mobilité" in t for t in textes)
    assert not any("Pays3" in t for t in textes)


def test_la_recherche_s_aligne_sur_le_contrat_de_l_offre(profil, offre, tmp_path):
    """Un CV envoyé pour un CDI n'annonce pas qu'on cherche aussi un stage :
    la liste complète dilue la candidature."""
    from app.documents.cv_render import rendre

    profil.contrats_acceptes = ["CDI", "V.I.E", "Stage", "CDD"]
    offre.type_contrat = "CDI"
    textes = _textes(rendre(profil, offre, MODELE, tmp_path / "CV.docx"))
    assert any("Recherche : CDI" in t for t in textes)
    assert not any("Stage" in t and "Recherche" in t for t in textes)


def test_un_contrat_hors_preferences_laisse_la_liste(profil, offre, tmp_path):
    """Mieux vaut dire ce qu'on cherche que de taire l'information."""
    from app.documents.cv_render import rendre

    profil.contrats_acceptes = ["CDI", "CDD"]
    offre.type_contrat = "Freelance"
    textes = _textes(rendre(profil, offre, MODELE, tmp_path / "CV.docx"))
    assert any("Recherche : CDI, CDD" in t for t in textes)


def test_une_offre_sans_contrat_laisse_la_liste(profil, offre, tmp_path):
    from app.documents.cv_render import rendre

    profil.contrats_acceptes = ["CDI", "CDD"]
    offre.type_contrat = ""
    textes = _textes(rendre(profil, offre, MODELE, tmp_path / "CV.docx"))
    assert any("Recherche : CDI, CDD" in t for t in textes)


def test_sans_contrat_la_ligne_disparait(profil, offre, tmp_path):
    """Plutôt qu'un « Recherche : — » qui fait document mal fusionné."""
    from app.documents.cv_render import rendre

    profil.contrats_acceptes = []
    textes = _textes(rendre(profil, offre, MODELE, tmp_path / "CV.docx"))
    assert not any("Recherche" in t for t in textes)


def _huit_puces(profil):
    profil.experiences = [{
        "entreprise": "Crédit Mutuel", "poste": "Gestionnaire",
        "debut": "2023", "fin": "2025",
        "description": "\n".join(f"Mission numéro {i} sur le portefeuille." for i in range(8)),
    }]
    return profil


def test_toutes_les_puces_du_profil_sont_rendues_par_defaut(profil, offre, tmp_path):
    """Elles étaient plafonnées à cinq, sans que le CV ait débordé."""
    cv = rendre(_huit_puces(profil), offre, MODELE, tmp_path / "CV.docx")
    assert len([t for t in _textes(cv) if t.startswith("Mission numéro")]) == 8


def test_une_ligne_coupee_dans_le_profil_reste_une_seule_puce():
    """Mesuré sur le profil réel : « (Budget 1,5 millions d' » puis « euros) »
    à la ligne — deux puces, la première tronquée, la seconde d'un mot."""
    from app.documents.cv_render import _decouper_en_puces

    assert _decouper_en_puces(
        "Analyse du marché immobilier parisien\n"
        "Recherche de nouveaux locaux professionnels (Budget 1,5 millions d'\n"
        "euros)\n"
        "Mise en place de crowdfunding\n"
        "suivi des contributeurs") == [
        "Analyse du marché immobilier parisien",
        "Recherche de nouveaux locaux professionnels (Budget 1,5 millions d'euros)",
        "Mise en place de crowdfunding suivi des contributeurs",
    ]
    # Une phrase finie suivie d'une minuscule reste deux puces : on ne devine pas.
    assert _decouper_en_puces("Clôture mensuelle.\nsuivi des KPI") == [
        "Clôture mensuelle.", "suivi des KPI"]


def _faux_pdf(monkeypatch, mod, pages_selon):
    """Remplace LibreOffice : le PDF « compte » `pages_selon(docx)` pages, et
    chaque essai est consigné avec le Word tel qu'il a été converti."""
    essais = []

    def convertir(source):
        document = docx.Document(str(source))
        essais.append(document)
        pdf = source.with_suffix(".pdf")
        pdf.write_bytes(b"%PDF-1.4\n" + b"/Type /Page \n" * pages_selon(document))
        return pdf

    monkeypatch.setattr(mod.pdf_outil, "convertir", convertir)
    return essais


def _marge_cm(document):
    return round(document.sections[0].left_margin.cm, 2)


def _puces(document):
    return [p.text for p in document.paragraphs if p.text.startswith("Mission numéro")]


def test_on_resserre_la_mise_en_page_avant_de_couper_des_puces(profil, offre, tmp_path, monkeypatch):
    """Deux pages au modèle tel quel et aux marges réduites, une page dès que
    les espacements sont divisés par deux : les huit puces restent."""
    from app.documents import dossier as mod

    titre = next(p for p in docx.Document(str(MODELE)).paragraphs if p.text == "Profil")
    espace_modele = titre.paragraph_format.space_before.pt

    def pages(document):
        rubrique = next(p for p in document.paragraphs if p.text == "Profil")
        return 1 if rubrique.paragraph_format.space_before.pt < espace_modele else 2

    essais = _faux_pdf(monkeypatch, mod, pages)
    cv, pdf, nombre, ajustement = mod._cv_sur_une_page(
        _huit_puces(profil), offre, MODELE, tmp_path, True)

    assert nombre == 1 and len(essais) == 3
    assert ajustement["palier"] == 2 and ajustement["puces_coupees"] == 0
    assert len(_puces(docx.Document(str(cv)))) == 8
    assert _marge_cm(essais[0]) > 1.5 and _marge_cm(essais[1]) == 1.5


def test_le_palier_retenu_est_consigne_dans_le_journal(profil, offre, tmp_path, monkeypatch):
    from app.documents import dossier as mod

    _faux_pdf(monkeypatch, mod, lambda d: 1 if _marge_cm(d) == 1.5 else 2)
    resultat = generer(profil, offre, tmp_path, MODELE,
                       redacteur=_redacteur_honnete, ouvrir_apres=False)
    journal = json.loads((resultat.dossier / "generation.json").read_text(encoding="utf-8"))
    assert journal["cv_mise_en_page"] == {"palier": 1, "mise_en_page": "marges à 1,5 cm",
                                          "puces_max": None, "puces_coupees": 0}
    assert not any("retirée" in a for a in resultat.avertissements)


def test_les_puces_ne_tombent_qu_apres_le_dernier_palier_et_jamais_sous_deux(
        profil, offre, tmp_path, monkeypatch):
    from app.documents import dossier as mod
    from app.documents.mise_en_page import DERNIER_PALIER, PALIERS

    essais = _faux_pdf(monkeypatch, mod, lambda d: 2)       # rien ne suffit
    cv, pdf, nombre, ajustement = mod._cv_sur_une_page(
        _huit_puces(profil), offre, MODELE, tmp_path, True)

    # Chaque palier avec huit puces, puis 7, 6… 2 puces au dernier palier.
    assert [len(_puces(e)) for e in essais] == [8] * len(PALIERS) + [7, 6, 5, 4, 3, 2]
    assert nombre == 2 and len(_puces(docx.Document(str(cv)))) == 2
    assert ajustement == {"palier": DERNIER_PALIER.numero, "mise_en_page": DERNIER_PALIER.libelle,
                          "puces_max": 2, "puces_coupees": 6}


def test_une_puce_coupee_est_signalee(profil, offre, tmp_path, monkeypatch):
    from app.documents import dossier as mod

    _faux_pdf(monkeypatch, mod, lambda d: 1 if len(_puces(d)) <= 6 else 2)
    resultat = generer(_huit_puces(profil), offre, tmp_path, MODELE,
                       redacteur=_redacteur_honnete, ouvrir_apres=False)
    assert resultat.mise_en_page["puces_coupees"] == 2
    assert any(a.startswith("2 puces d'expérience retirées") for a in resultat.avertissements)


def test_les_planchers_ne_sont_jamais_franchis(tmp_path):
    """Corps jamais sous 10 pt, marges jamais sous 1,27 cm — titres réduits
    aussi, qu'ils soient définis sur le style ou sur le texte."""
    import re
    import shutil
    import zipfile

    from app.documents.mise_en_page import DERNIER_PALIER, appliquer

    def tailles(chemin):
        with zipfile.ZipFile(chemin) as archive:
            xml = "".join(archive.read(n).decode("utf-8") for n in
                          ("word/document.xml", "word/styles.xml"))
        return [int(v) for v in re.findall(r'<w:szCs? w:val="(\d+)"', xml)]

    copie = tmp_path / "CV.docx"
    shutil.copy(MODELE, copie)
    avant = tailles(copie)
    appliquer(copie, DERNIER_PALIER)
    apres = tailles(copie)

    assert len(avant) == len(apres)
    for a, b in zip(avant, apres):
        assert b == a if a <= 20 else b == max(20, a - 2)   # demi-points : 20 = 10 pt
    assert max(apres) < max(avant), "le nom et les titres sont réduits aussi"
    document = docx.Document(str(copie))
    for section in document.sections:
        for marge in (section.top_margin, section.bottom_margin,
                      section.left_margin, section.right_margin):
            assert marge.cm >= 1.27


def test_le_plafond_de_puces_est_respecte(profil, offre, tmp_path):
    """Passé explicitement, en dernier recours de `dossier.py`."""
    cv = rendre(_huit_puces(profil), offre, MODELE, tmp_path / "CV.docx", max_puces=2)
    assert len([t for t in _textes(cv) if t.startswith("Mission numéro")]) == 2


def test_sans_libreoffice_le_cv_part_entier(profil, offre, tmp_path, monkeypatch):
    """Faute de pouvoir mesurer, mieux vaut un CV complet qu'un CV amputé au
    hasard — et dans la mise en page du modèle, pas à moitié resserrée."""
    from app.documents import dossier as mod

    def refuse(source):
        raise RuntimeError("LibreOffice absent")

    monkeypatch.setattr(mod.pdf_outil, "convertir", refuse)
    cv, pdf, pages, ajustement = mod._cv_sur_une_page(
        _huit_puces(profil), offre, MODELE, tmp_path, True)
    assert cv.exists()
    assert pdf is None and pages == 0
    assert len([t for t in _textes(cv) if t.startswith("Mission numéro")]) == 8
    assert _marge_cm(docx.Document(str(cv))) == _marge_cm(docx.Document(str(MODELE)))
    assert ajustement["palier"] == 0 and ajustement["puces_coupees"] == 0


def test_le_dossier_consigne_ce_qu_un_ats_lira_du_cv(profil, offre, tmp_path):
    """La lecture porte sur le fichier produit, pas sur le profil : c'est lui
    que le logiciel de recrutement convertit en texte. Le modèle livré doit
    rester lisible — une colonne, des rubriques classiques, le nom en tête."""
    import json as _json

    resultat = generer(profil, offre, tmp_path, MODELE,
                       redacteur=_redacteur_honnete, ouvrir_apres=False)
    lecture = resultat.lecture_ats
    assert lecture["lisible"] and lecture["structure"] == []
    assert lecture["coordonnees"]["nom_en_tete"]
    assert set(lecture["rubriques"]) == {"expériences", "formation", "compétences"}
    assert not [a for a in resultat.avertissements if a.startswith("Lecture ATS")]
    journal = _json.loads((resultat.dossier / "generation.json").read_text(encoding="utf-8"))
    assert journal["lecture_ats"]["rubriques"] == lecture["rubriques"]
