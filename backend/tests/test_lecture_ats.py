"""Ce qu'un logiciel de recrutement lira du CV : la structure du fichier, le
texte extrait, les mots de l'annonce au mot près — et ce qu'on sait de chaque
logiciel, sans rien lui prêter."""

import zipfile

import pytest
from docx import Document

from app.documents import ats, lecture_ats
from app.models import Offer, Profile
from app.scoring.couverture import competences_en_phrases, manques_recurrents


@pytest.fixture
def profil() -> Profile:
    return Profile(
        prenom="Maxime", nom="Nicolas", email="maxime@exemple.fr", telephone="06 00 00 00 00",
        titre_vise="Analyste risques", annees_experience=2,
        langues=[{"code": "fr", "libelle": "Français", "niveau": "natif"}],
        skills=[{"nom": "Excel"}, {"nom": "Risque de crédit"},
                {"nom": "Connaissance du fonctionnement des différents produits boursiers"}],
        experiences=[{"entreprise": "Banque", "poste": "Analyste",
                      "description": "Suivi des risques de crédit et des créances."}])


def _offre(description="", **champs) -> Offer:
    base = dict(source="t", source_id="1", titre="Analyste risques (H/F)", entreprise="Banque",
                lieu="Paris", description_brute=description, raw={})
    return Offer(**(base | champs))


def _cv(tmp_path, *lignes, nom="CV.docx"):
    document = Document()
    for ligne in lignes:
        document.add_paragraph(ligne)
    chemin = tmp_path / nom
    document.save(chemin)
    return chemin


CV_NORMAL = (
    "MAXIME NICOLAS", "Analyste risques", "Paris | 06 00 00 00 00 | maxime@exemple.fr",
    "Compétences", "Excel, Risque de crédit, reporting",
    "Expériences professionnelles", "Analyste", "Banque — Paris — Septembre 2023 – Septembre 2025",
    "Suivi des risques de crédit et des créances pour une clientèle d'entreprises exportatrices.",
    "Formation", "Master 2 Finance", "EM Normandie — 2020 - 2025",
)

ANNONCE = ("Vous suivez les risques de crédit. Risques de marché, reporting des risques, "
           "reporting réglementaire et reporting mensuel. Solvabilité des contreparties : "
           "solvabilité, solvabilité. Provisionnement, provisionnement, provisionnement.")


# --- La structure du Word -----------------------------------------------------

def test_un_cv_a_une_colonne_n_a_aucun_defaut(tmp_path):
    assert lecture_ats.defauts_de_structure(_cv(tmp_path, *CV_NORMAL)) == []


def test_un_tableau_est_signale(tmp_path):
    document = Document()
    document.add_paragraph("MAXIME NICOLAS")
    document.add_table(rows=1, cols=2).cell(0, 0).text = "Compétences"
    chemin = tmp_path / "CV.docx"
    document.save(chemin)
    defauts = lecture_ats.defauts_de_structure(chemin)
    assert len(defauts) == 1 and "tableau" in defauts[0]


def test_des_coordonnees_dans_l_en_tete_sont_signalees(tmp_path):
    document = Document()
    document.add_paragraph("MAXIME NICOLAS")
    document.sections[0].header.paragraphs[0].text = "maxime@exemple.fr"
    chemin = tmp_path / "CV.docx"
    document.save(chemin)
    assert any("en-tête" in d for d in lecture_ats.defauts_de_structure(chemin))


def test_un_fichier_qui_n_est_pas_un_word_ne_fait_rien_planter(tmp_path):
    faux = tmp_path / "CV.docx"
    faux.write_bytes(b"pas un zip")
    assert lecture_ats.defauts_de_structure(faux) == []
    vide = tmp_path / "vide.docx"
    with zipfile.ZipFile(vide, "w"):
        pass
    assert lecture_ats.defauts_de_structure(vide) == []


# --- Le texte lu --------------------------------------------------------------

def test_un_cv_normal_est_lu_sans_avertissement(tmp_path, profil):
    lecture = lecture_ats.lire(_cv(tmp_path, *CV_NORMAL), None, profil, _offre(ANNONCE))
    assert lecture["lisible"] and lecture["avertissements"] == []
    assert lecture["coordonnees"] == {"nom_en_tete": True, "email": True, "telephone": True}
    assert lecture["rubriques"] == ["expériences", "formation", "compétences"]
    # « (H/F) » retiré : c'est l'intitulé tel qu'un recruteur le tape.
    assert lecture["intitule_exact"]


def test_une_rubrique_au_titre_inhabituel_est_signalee(tmp_path, profil):
    lignes = [l.replace("Expériences professionnelles", "Mon aventure") for l in CV_NORMAL]
    lecture = lecture_ats.lire(_cv(tmp_path, *lignes), None, profil, _offre(ANNONCE))
    assert lecture["rubriques"] == ["formation", "compétences"]
    assert any("rubrique non reconnue : expériences" in a for a in lecture["avertissements"])


def test_des_coordonnees_absentes_du_texte_sont_signalees(tmp_path, profil):
    lignes = [l.replace(" | 06 00 00 00 00 | maxime@exemple.fr", "") for l in CV_NORMAL]
    lecture = lecture_ats.lire(_cv(tmp_path, *lignes), None, profil, _offre(ANNONCE))
    assert lecture["coordonnees"]["email"] is False and lecture["coordonnees"]["telephone"] is False
    assert sum("Lecture ATS" in a for a in lecture["avertissements"]) == 2


def test_un_pdf_sans_texte_est_signale(tmp_path, profil):
    """Un PDF fait d'une image : un analyseur n'y trouve rien."""
    from pypdf import PdfWriter

    pdf = tmp_path / "CV.pdf"
    ecrivain = PdfWriter()
    ecrivain.add_blank_page(width=595, height=842)
    with pdf.open("wb") as fichier:
        ecrivain.write(fichier)
    lecture = lecture_ats.lire(_cv(tmp_path, *CV_NORMAL), pdf, profil, _offre(ANNONCE))
    assert lecture["lisible"] is False
    assert any("ne contient pas de texte lisible" in a for a in lecture["avertissements"])
    assert lecture_ats.resume(lecture) == ""


# --- Les mots de l'annonce ----------------------------------------------------

def test_les_mots_de_l_annonce_sont_ranges_selon_ce_que_le_cv_en_dit(tmp_path, profil):
    """Une recherche par mot-clé ne connaît pas les synonymes : « au mot près »
    et « dit autrement » ne sont pas la même chose pour un recruteur."""
    lecture = lecture_ats.lire(_cv(tmp_path, *CV_NORMAL), None, profil, _offre(ANNONCE))
    termes = lecture["termes"]
    assert {"risques", "reporting"} <= set(termes["au_mot_pres"])
    assert "provisionnement" in termes["absents"]
    assert lecture["termes_trouves"] == len(termes["au_mot_pres"]) + len(termes["forme_voisine"])
    assert 0 < lecture["taux_litteral"] < 100
    assert "mots-clés de l'annonce" in lecture_ats.resume(lecture)


def test_un_pluriel_est_une_forme_voisine_pas_un_mot_absent():
    rangement = lecture_ats.mots_de_l_annonce(
        "Suivi du risque de marché", _offre("Risques, risques et encore risques."))
    assert rangement["forme_voisine"] == ["risques"] and rangement["absents"] == []


# --- Ce qu'on sait de chaque logiciel -----------------------------------------

def test_le_logiciel_vient_du_site_de_l_employeur():
    offre = _offre(raw={"employeur": "Banque", "logiciel": "workday"})
    assert ats.logiciel_de(offre) == "workday"
    assert ats.fiche_de(offre).nom == "Workday"


def test_le_logiciel_se_reconnait_a_l_adresse_de_candidature():
    """Une offre d'agrégateur dont le lien mène au site carrières."""
    par_lien = _offre(url="https://banque.wd3.myworkdayjobs.com/fr-FR/Careers/job/123")
    par_contact = _offre(raw={"contact": {"urlPostulation": "https://banque.taleo.net/careersection/2/x"}})
    assert ats.logiciel_de(par_lien) == "workday"
    assert ats.fiche_de(par_contact).format == "docx"


def test_un_logiciel_inconnu_n_a_pas_de_fiche():
    """On ne prête pas à un site les règles d'un autre."""
    assert ats.fiche_de(_offre(url="https://exemple.fr/offre/1")) is None
    assert ats.fiche_de(_offre(raw={"logiciel": "plan_du_site"})) is None


def test_un_logiciel_sans_source_fiable_ne_recoit_que_le_conseil_commun():
    fiche = ats.fiche_de(_offre(raw={"logiciel": "lever"}))
    assert fiche.preuve == ats.INCONNU and fiche.conseil == ats.CONSEIL_COMMUN


def test_chaque_fiche_documentee_cite_sa_source():
    for fiche in ats.FICHES.values():
        assert fiche.preuve in (ats.DOCUMENTE, ats.CONVERGENT)
        assert fiche.sources and all(s.startswith("https://") for s in fiche.sources)


# --- Les mots qui manquent au profil ------------------------------------------

def test_les_manques_se_comptent_sur_l_ensemble_des_offres(profil):
    """Une offre ne dit rien ; plusieurs dessinent le vocabulaire du métier. Un
    mot toujours accompagné du même voisin est rendu avec lui."""
    offres = [_offre(f"Poste en middle office. Le middle office suit les opérations, "
                     f"middle office numéro {n}.", source_id=str(n)) for n in range(4)]
    offres.append(_offre("Titrisation, titrisation, titrisation.", source_id="9"))
    manques = dict(manques_recurrents(profil, offres))
    assert manques.get("middle office") == 4
    assert "titrisation" not in manques, "une seule offre ne fait pas un manque récurrent"
    assert "risques" not in manques, "le profil le dit déjà"


def test_les_competences_en_phrases_sont_reperees(profil):
    assert competences_en_phrases(profil) == [
        "Connaissance du fonctionnement des différents produits boursiers"]
