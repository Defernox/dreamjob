"""L'intitulé de poste sur le CV et dans la lettre, et ce qui entoure l'envoi.

Tous les intitulés ci-dessous sont réels : relevés dans la base de l'utilisateur
le jour où l'on a mesuré que 45 % des offres pertinentes auraient mis « (H/F) »
sous son nom.
"""

import json
import zipfile
from pathlib import Path

import pytest

from app.documents.intitule import au_poste, intitule_pour_cv, nettoyer_intitule
from app.documents.lettre import nettoyer
from app.models import Offer, Profile

MODELE = Path(__file__).resolve().parents[2] / "templates" / "cv_modele.docx"
avec_modele = pytest.mark.skipif(not MODELE.exists(), reason="cv_modele.docx absent")


# --- Nettoyage de l'intitulé -------------------------------------------------


@pytest.mark.parametrize("brut, lieu, attendu", [
    ("Analyste Risques Financiers (H/F)- PARIS (H/F)", "75 - Paris 8e", "Analyste Risques Financiers"),
    ("CDI - Gestionnaire de comptes Middle Office Employeurs (54) (H/F)", "54 - Nancy",
     "Gestionnaire de comptes Middle Office Employeurs"),
    ("ANALYSTE RISQUES CDD - 12 mois H/F", "", "Analyste risques"),
    ("Directeur des Finances H/F (CDI)", "", "Directeur des Finances"),
    ("Conseiller financier - 100% télétravail (H/F)", "", "Conseiller financier"),
    ("Gestionnaire Middle Office F/H", "", "Gestionnaire Middle Office"),
    ("VIE/PANGEO Management Controller M/W/X (H/F)", "", "PANGEO Management Controller"),
    ("Analyste quantitatif risques de crédit H/F Lille", "59 - Lille",
     "Analyste quantitatif risques de crédit"),
    ("Stage de fin d'études - Analyste crédit", "", "Analyste crédit"),
    ("CHARGE(E) COMPTABLE ET FINANCIER (H/F)", "", "Chargé(e) comptable et financier"),
    ("RESPONSABLE ADMINISTRATIF ET FINANCIER        (H/F)", "",
     "Responsable administratif et financier"),
])
def test_l_intitule_perd_ce_qui_ne_concerne_pas_le_candidat(brut, lieu, attendu):
    assert nettoyer_intitule(brut, lieu) == attendu


@pytest.mark.parametrize("brut, lieu", [
    ("Front-Office Analyst", "75 - Paris"),            # trait d'union d'un mot composé
    ("Cash-flow Analyst", ""),                          # « h-f » au milieu d'un mot
    ("Analyste - La Banque Postale", "92 - La Défense"),  # « La » n'est pas un lieu
    ("Développeur Algo Trading - Bonds", "75 - Paris"),  # une spécialité, pas une ville
    ("Business Analyst Flux de Paiement", ""),           # casse choisie par l'annonceur
])
def test_ce_qui_n_est_pas_du_bruit_reste_intact(brut, lieu):
    """Mesuré avant d'écrire la règle : le segment après un tiret final est
    rarement un lieu — « - Bank », « - Trading », « - Middle Office »."""
    assert nettoyer_intitule(brut, lieu) == brut


def test_un_intitule_vide_apres_nettoyage_cede_au_titre_vise():
    """« Stage : Finance » deviendrait « Finance », qui ne dit pas quel poste on vise."""
    assert intitule_pour_cv("Stage : Finance", "Paris", "Analyste financier") == "Analyste financier"


DOUBLE = "Auditeur comptable et financier / Auditrice comptable et financière (H/F)"
TRONQUE = "Directeur administratif et financier / Directrice administrative (H/F)"


def test_l_intitule_double_suit_l_accord_du_profil():
    assert intitule_pour_cv(DOUBLE, "", "Analyste", "masculin") == "Auditeur comptable et financier"
    assert intitule_pour_cv(DOUBLE, "", "Analyste", "feminin") == "Auditrice comptable et financière"


def test_sans_accord_on_ne_choisit_pas_le_genre_a_la_place_du_candidat():
    """Prendre la première moitié reviendrait à supposer le masculin."""
    assert intitule_pour_cv(DOUBLE, "", "Analyste financier", "") == "Analyste financier"


def test_une_moitie_feminine_tronquee_par_la_source_n_est_pas_retenue():
    """France Travail coupe parfois la seconde moitié : « Directrice
    administrative » n'est pas le poste, c'est un morceau de titre."""
    assert intitule_pour_cv(TRONQUE, "", "Analyste financier", "feminin") == "Analyste financier"


# --- Élision -----------------------------------------------------------------


@pytest.mark.parametrize("intitule, attendu", [
    ("Analyste crédit", "d'Analyste crédit"),
    ("Assistant de gestion", "d'Assistant de gestion"),
    ("Contrôleur de gestion", "de Contrôleur de gestion"),
    ("Head of Finance", "de Head of Finance"),
])
def test_l_objet_elide_devant_une_voyelle(intitule, attendu):
    assert au_poste(intitule) == attendu


@pytest.mark.parametrize("brut, attendu", [
    ("le poste de « Analyste Quantitatif Risques »", "le poste d'« Analyste Quantitatif Risques »"),
    ("un portefeuille de entreprises", "un portefeuille d'entreprises"),
    ("chez Amundi et de EY", "chez Amundi et d'EY"),
    ("de A à Z", "de A à Z"),
    ("de onze entreprises", "de onze entreprises"),
    ("de Head of Finance", "de Head of Finance"),
])
def test_la_lettre_rendue_est_elidee(brut, attendu):
    """« le poste de « Analyste … » » : relevé dans une vraie lettre."""
    assert nettoyer(brut) == attendu


# --- Ce qui part chez le recruteur -------------------------------------------


def _profil(**kw):
    base = dict(prenom="Maxime", nom="Nicolas", skills=[{"nom": "Excel"}],
                experiences=[{"entreprise": "Crédit Mutuel", "poste": "Gestionnaire"}],
                formations=[{"diplome": "Master", "etablissement": "EM Normandie"}])
    return Profile(**{**base, **kw})


def _offre():
    return Offer(source="t", source_id="1", titre="Analyste crédit (H/F)",
                 entreprise="Banque", lieu="75 - Paris")


def _generer(racine: Path, profil: Profile):
    from app.documents.dossier import generer

    return generer(profil, _offre(), racine, MODELE,
                   redacteur=lambda s, m: "Mon parcours au Crédit Mutuel me prépare. " * 25,
                   ouvrir_apres=False)


@avec_modele
def test_les_fichiers_portent_le_nom_du_candidat(tmp_path):
    """Le recruteur reçoit cinquante `CV.pdf` et doit renommer le vôtre pour le
    retrouver. Sans accents : certains ATS abîment les noms non ASCII."""
    resultat = _generer(tmp_path, _profil(prenom="Élodie", nom="Lefèvre"))
    noms = {f.name for f in resultat.fichiers}
    assert "CV_Elodie_Lefevre.docx" in noms
    assert "Lettre_de_motivation_Elodie_Lefevre.docx" in noms


@avec_modele
def test_les_metadonnees_nomment_le_candidat(tmp_path):
    """Le CV partait signé « Un-named », la lettre « python-docx »."""
    resultat = _generer(tmp_path, _profil())
    for fichier in (f for f in resultat.fichiers if f.suffix == ".docx"):
        core = zipfile.ZipFile(fichier).read("docProps/core.xml").decode("utf-8")
        assert "<dc:creator>Maxime Nicolas</dc:creator>" in core, fichier.name
        assert "Un-named" not in core and "python-docx" not in core, fichier.name


@avec_modele
def test_l_objet_de_la_lettre_est_propre(tmp_path):
    import docx

    resultat = _generer(tmp_path, _profil())
    lettre = next(f for f in resultat.fichiers if f.name.startswith("Lettre") and f.suffix == ".docx")
    objet = next(p.text for p in docx.Document(str(lettre)).paragraphs if p.text.startswith("Objet"))
    assert objet == "Objet : candidature au poste d'Analyste crédit"


@avec_modele
def test_une_regeneration_efface_les_fichiers_aux_anciens_noms(tmp_path):
    """Un dossier produit avant le changement de nom contient `CV.pdf` : régénéré,
    il aurait gardé l'ancien CV à côté du nouveau."""
    from app.documents.dossier import nom_dossier

    dossier = tmp_path / nom_dossier(_offre())
    dossier.mkdir(parents=True)
    for ancien in ("CV.docx", "CV.pdf", "Lettre_de_motivation.docx"):
        (dossier / ancien).write_bytes(b"ancien")
    (dossier / "mes-notes.txt").write_text("à garder", encoding="utf-8")

    _generer(tmp_path, _profil())
    assert not (dossier / "CV.pdf").exists()
    assert not (dossier / "CV.docx").exists()
    assert (dossier / "mes-notes.txt").exists(), "un fichier de l'utilisateur a été effacé"


@avec_modele
def test_un_changement_de_nom_n_abandonne_pas_les_fichiers_precedents(tmp_path):
    """Le journal consigne ce qui a été produit : si le candidat corrige son nom,
    la génération suivante sait encore quoi effacer."""
    from app.documents.dossier import nom_dossier

    _generer(tmp_path, _profil(nom="Nicola"))
    dossier = tmp_path / nom_dossier(_offre())
    assert (dossier / "CV_Maxime_Nicola.docx").exists()
    consignes = json.loads((dossier / "generation.json").read_text(encoding="utf-8"))["fichiers"]
    assert "CV_Maxime_Nicola.docx" in consignes

    _generer(tmp_path, _profil(nom="Nicolas"))
    assert not (dossier / "CV_Maxime_Nicola.docx").exists()
    assert (dossier / "CV_Maxime_Nicolas.docx").exists()


def test_le_dossier_porte_l_intitule_nettoye():
    """Brut, le dossier s'appelait « …-analyste-risques-financiers-h-f-paris-h »."""
    from datetime import date

    from app.documents.dossier import nom_dossier

    offre = Offer(source="t", source_id="1", entreprise="Caixa Geral de Depósitos",
                  titre="Analyste Risques Financiers (H/F)- PARIS (H/F)", lieu="75 - Paris")
    assert nom_dossier(offre, date(2026, 9, 24)) == \
        "2026-09-24-caixa-geral-de-depositos-analyste-risques-financiers"


def test_l_employeur_et_le_lieu_ne_sont_pas_des_competences_manquantes():
    """L'avertissement annonçait « caixa, depositos, geral, paris » comme des
    termes à combler."""
    from app.scoring.couverture import mots_cles_non_couverts

    offre = Offer(source="t", source_id="1", entreprise="Caixa Geral de Depósitos",
                  titre="Analyste risques", lieu="75 - Paris", pays="France",
                  description_brute=("Caixa Geral de Depósitos recrute à Paris. " * 4
                                     + "Vous maîtrisez le provisionnement IFRS 9. " * 3))
    manquants = mots_cles_non_couverts(_profil(), offre)
    assert not {"caixa", "geral", "depositos", "paris", "france"} & set(manquants), manquants
    assert "provisionnement" in manquants
