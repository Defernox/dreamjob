"""Le CV ciblé : le modèle propose, le code vérifie chaque puce.

Tous les tests passent par un faux modèle : ce qui est testé, ce sont les
contrôles et leur intégration, pas la qualité d'une réécriture.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.documents.ciblage import (
    CorrectionCiblage,
    ExperienceCiblee,
    PuceCorrigee,
    PropositionCiblage,
    cibler,
    verifier_puce,
    verifier_resume,
)
from app.llm.client import LlmErreur
from app.llm.redaction import AppelAnthropic, cout_usd
from app.models import Offer, Profile

MODELE = Path(__file__).resolve().parents[2] / "templates" / "cv_modele.docx"
avec_modele = pytest.mark.skipif(not MODELE.exists(), reason="cv_modele.docx absent")

# Les puces réelles du candidat.
RISQUE = ("Gestion des risques de crédit à l'export : Évaluer la solvabilité des clients "
          "internationaux, suivre les créances et mettre en place des garanties adaptées "
          "pour limiter les risques de non-paiement.")
PORTEFEUILLE = ("Gestion quotidienne d'un portefeuille de 15 à 25 entreprises représentant "
                "un chiffre d'affaires de 50 à 75 millions d'euros.")


def _profil():
    return Profile(
        prenom="Maxime", nom="Nicolas", skills=[{"nom": "Analyse financière"}],
        resume="Parcours en finance.",
        experiences=[
            {"entreprise": "Aventure Fantastique", "poste": "Assistant financier",
             "debut": "Mai 2021", "fin": "Juillet 2021", "description": RISQUE},
            {"entreprise": "Crédit Mutuel", "poste": "Gestionnaire de portefeuille export",
             "debut": "Septembre 2023", "fin": "Septembre 2025", "description": PORTEFEUILLE},
        ],
        formations=[{"diplome": "Master 2 Finance", "etablissement": "EM Normandie"}])


def _offre():
    return Offer(source="t", source_id="1", titre="Analyste risque de crédit (H/F)",
                 entreprise="Banque", lieu="75 - Paris",
                 description_brute="Analyse du risque de crédit des contreparties, "
                                   "suivi des encours. Maîtrise IFRS 9 et Bloomberg. "
                                   "5 ans d'expérience.")


class FauxModele:
    """Rend `proposition` au premier tour, `correction` au second (ou rien)."""

    def __init__(self, proposition, erreur: Exception | None = None, correction=None):
        self.proposition = proposition
        self.erreur = erreur
        self.correction = correction or CorrectionCiblage(puces=[])
        self.appels = 0
        self.messages = []
        self.consommation = []

    def structure(self, systeme, message, format_sortie):
        self.appels += 1
        self.messages.append(message)
        self.consommation.append({"etape": "ciblage", "modele": "faux", "entree": 3000,
                                  "sortie": 800, "cache_lu": 0, "usd": 0.014})
        if self.erreur:
            raise self.erreur
        return self.correction if format_sortie is CorrectionCiblage else self.proposition


HONNETE = "Analyse du risque de crédit export : évaluation de la solvabilité des clients internationaux, suivi des créances et mise en place de garanties contre le risque de non-paiement."
MENSONGE = "Modélisation du risque de crédit sous IFRS 9 et suivi des encours sur Bloomberg."


def _proposition(resume="Profil finance orienté risque de crédit export.", puces_0=None, puces_1=None):
    return PropositionCiblage(resume=resume, experiences=[
        ExperienceCiblee(numero=0, puces=puces_0 or [HONNETE]),
        ExperienceCiblee(numero=1, puces=puces_1 or [PORTEFEUILLE]),
    ])


# --- Le tri entre honnête et mensonge ---------------------------------------


def test_une_reformulation_honnete_est_retenue():
    ciblage = cibler(_profil(), _offre(), {0: [RISQUE], 1: [PORTEFEUILLE]},
                     FauxModele(_proposition()))
    assert ciblage.puces[0] == [HONNETE]
    assert ciblage.journal["puces_reecrites"] == 1
    assert ciblage.journal["puces_inchangees"] == 1


def test_une_puce_qui_ment_retombe_sur_l_originale():
    """Ni la modélisation, ni IFRS 9, ni Bloomberg ne figurent dans la puce : ils
    viennent de l'annonce. La puce d'origine est gardée, le refus consigné."""
    ciblage = cibler(_profil(), _offre(), {0: [RISQUE], 1: [PORTEFEUILLE]},
                     FauxModele(_proposition(puces_0=[MENSONGE])))
    assert ciblage.puces[0] == [RISQUE]
    refus = ciblage.journal["puces_refusees"][0]
    assert refus["proposee"] == MENSONGE
    assert any("IFRS" in r for r in refus["raisons"])


@pytest.mark.parametrize("proposee, motif", [
    ("Gestion quotidienne d'un portefeuille de 40 entreprises.", "nombre"),
    ("Gestion d'un portefeuille de 15 à 25 entreprises exportatrices, pilotage du provisionnement.", "notion"),
    ("Gestion quotidienne chez BNP Paribas d'un portefeuille de 15 à 25 entreprises.", "nom propre"),
])
def test_chaque_type_d_ajout_est_refuse(proposee, motif):
    raisons = verifier_puce(PORTEFEUILLE, proposee, _offre())
    assert any(motif in r for r in raisons), raisons


def test_une_puce_qui_double_de_longueur_est_refusee():
    """Le CV doit tenir sur une page : une puce ne peut pas enfler."""
    longue = PORTEFEUILLE + " " + PORTEFEUILLE
    assert any("trop longue" in r for r in verifier_puce(PORTEFEUILLE, longue, _offre()))


def test_une_experience_desalignee_est_ignoree_et_non_reparee():
    """Deux puces rendues pour une seule : on ne devine pas laquelle correspond."""
    ciblage = cibler(_profil(), _offre(), {0: [RISQUE], 1: [PORTEFEUILLE]},
                     FauxModele(_proposition(puces_0=[HONNETE, HONNETE])))
    assert 0 not in ciblage.puces
    assert 0 in ciblage.journal["experiences_ignorees"]


# --- Le résumé ---------------------------------------------------------------


def test_un_resume_qui_reprend_un_chiffre_de_l_annonce_est_refuse():
    """« 5 ans d'expérience » figure dans l'OFFRE : c'est précisément pourquoi il
    ne peut pas figurer dans le résumé du candidat."""
    raisons = verifier_resume("Analyste avec 5 ans d'expérience du risque de crédit.",
                              _profil(), _offre())
    assert any("nombre" in r for r in raisons)


def test_un_resume_a_la_premiere_personne_est_refuse():
    assert verifier_resume("Je suis analyste du risque de crédit.", _profil(), _offre())


def test_un_resume_refuse_laisse_celui_du_profil():
    ciblage = cibler(_profil(), _offre(), {0: [RISQUE], 1: [PORTEFEUILLE]},
                     FauxModele(_proposition(resume="Je cumule 5 ans d'expérience.")))
    assert ciblage.resume is None
    assert ciblage.journal["resume"]["raisons"]


# --- L'intégration au dossier -------------------------------------------------


def _generer(tmp_path, cibleur, redacteur=None):
    from app.documents.dossier import generer

    return generer(_profil(), _offre(), tmp_path, MODELE,
                   redacteur=redacteur or (lambda s, m: "Mon parcours au Crédit Mutuel me prépare. " * 25),
                   ouvrir_apres=False, cibleur=cibleur)


def _textes_du_cv(resultat) -> str:
    import docx

    cv = next(f for f in resultat.fichiers if f.name.startswith("CV") and f.suffix == ".docx")
    return "\n".join(p.text for p in docx.Document(str(cv)).paragraphs)


@avec_modele
def test_le_cv_rendu_porte_le_resume_et_les_puces_ciblees(tmp_path):
    resultat = _generer(tmp_path, FauxModele(_proposition()))
    texte = _textes_du_cv(resultat)
    assert "Profil finance orienté risque de crédit export." in texte
    assert "Analyse du risque de crédit export" in texte


@avec_modele
def test_le_ciblage_n_est_demande_qu_une_fois(tmp_path):
    """La mise en page rappelle le rendu jusqu'à quatre fois : le ciblage, lui,
    est calculé avant — sinon on le paierait à chaque essai."""
    modele = FauxModele(_proposition())
    _generer(tmp_path, modele)
    assert modele.appels == 1


@avec_modele
def test_un_ciblage_en_echec_livre_quand_meme_le_cv(tmp_path):
    resultat = _generer(tmp_path, FauxModele(None, erreur=LlmErreur("Crédits épuisés")))
    assert any(f.name.startswith("CV") for f in resultat.fichiers)
    assert any("non adapté" in a for a in resultat.avertissements)
    assert RISQUE.split(":")[0] in _textes_du_cv(resultat)


@avec_modele
def test_le_cout_du_dossier_est_consigne(tmp_path):
    resultat = _generer(tmp_path, FauxModele(_proposition()))
    journal = json.loads((resultat.dossier / "generation.json").read_text(encoding="utf-8"))
    assert journal["cout_usd"] == 0.014   # aucun refus : pas de second tour
    assert journal["consommation"][0]["etape"] == "ciblage"
    assert journal["ciblage"]["puces_reecrites"] == 1


# --- L'appel à Anthropic -----------------------------------------------------


def _usage(entree=1_000_000, sortie=0, lu=0, ecrit=0):
    return SimpleNamespace(input_tokens=entree, output_tokens=sortie,
                           cache_read_input_tokens=lu, cache_creation_input_tokens=ecrit)


def test_le_cout_suit_le_tarif_du_modele():
    tarifs = {"claude-opus-5-5": (4.0, 20.0)}
    assert cout_usd("claude-opus-5-5", _usage(1_000_000, 100_000), tarifs) == pytest.approx(6.0)
    # Le cache lu coûte un dixième du tarif d'entrée.
    assert cout_usd("claude-opus-5-5", _usage(0, 0, lu=1_000_000), tarifs) == pytest.approx(0.4)


def test_un_modele_sans_tarif_connu_ne_s_invente_pas_de_cout():
    assert cout_usd("modele-inconnu", _usage(), {}) == 0.0


class _FauxFlux:
    def __init__(self, reponse):
        self.reponse = reponse

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.reponse


def _appel_avec(reponse, monkeypatch):
    from app.config import reglages

    client = SimpleNamespace(_anthropic=lambda: SimpleNamespace(
        messages=SimpleNamespace(stream=lambda **kw: _FauxFlux(reponse))))
    return AppelAnthropic(reglages(), etape="lettre", modele="claude-opus-5-5",
                          effort="medium", max_tokens=16000, client=client)


@pytest.mark.parametrize("fin, attendu", [("refusal", "décliné"), ("max_tokens", "tronquée")])
def test_un_refus_ou_une_troncature_n_est_pas_livre(fin, attendu, monkeypatch):
    """Une lettre tronquée par le budget de jetons partirait coupée en plein
    paragraphe : c'est une erreur, pas un texte."""
    reponse = SimpleNamespace(stop_reason=fin, usage=_usage(1000, 500),
                              content=[SimpleNamespace(type="text", text="Début de lettre")])
    appel = _appel_avec(reponse, monkeypatch)
    with pytest.raises(LlmErreur, match=attendu):
        appel("systeme", "message")
    assert appel.consommation, "un appel payé doit être relevé, même raté"


def test_seul_le_texte_est_livre_pas_la_reflexion(monkeypatch):
    reponse = SimpleNamespace(stop_reason="end_turn", usage=_usage(1000, 500), content=[
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text="Corps de la lettre."),
    ])
    assert _appel_avec(reponse, monkeypatch)("s", "m") == "Corps de la lettre."


# --- Le second tour ------------------------------------------------------------

MITIGATION = ("Évaluation de la solvabilité des clients internationaux, suivi des créances "
              "et garanties pour limiter les risques de non-paiement.")


def test_la_faute_est_nommee_et_la_version_honnete_retenue():
    """Premier tour : « contrôle » ajouté, refusé. Second tour : le modèle reçoit
    la raison du refus et rend une version sans ajout, qui passe."""
    modele = FauxModele(
        _proposition(puces_0=["Contrôle et " + HONNETE[0].lower() + HONNETE[1:]]),
        correction=CorrectionCiblage(puces=[PuceCorrigee(numero=0, position=0, puce=HONNETE)]))
    ciblage = cibler(_profil(), _offre(), {0: [RISQUE], 1: [PORTEFEUILLE]}, modele)

    assert modele.appels == 2
    assert "REFUSÉE CAR" in modele.messages[1] and "controle" in modele.messages[1]
    assert ciblage.puces[0] == [HONNETE]
    assert ciblage.journal["puces_corrigees"] == 1
    assert ciblage.journal["puces_refusees"] == []


def test_une_correction_qui_ment_encore_reste_refusee():
    modele = FauxModele(
        _proposition(puces_0=[MENSONGE]),
        correction=CorrectionCiblage(puces=[PuceCorrigee(numero=0, position=0, puce=MENSONGE)]))
    ciblage = cibler(_profil(), _offre(), {0: [RISQUE], 1: [PORTEFEUILLE]}, modele)
    assert ciblage.puces[0] == [RISQUE]
    assert len(ciblage.journal["puces_refusees"]) == 1


def test_sans_refus_il_n_y_a_pas_de_second_tour():
    modele = FauxModele(_proposition())
    cibler(_profil(), _offre(), {0: [RISQUE], 1: [PORTEFEUILLE]}, modele)
    assert modele.appels == 1


def test_une_correction_en_echec_garde_le_premier_tour():
    class Capricieux(FauxModele):
        def structure(self, systeme, message, format_sortie):
            if format_sortie is CorrectionCiblage:
                raise LlmErreur("surcharge")
            return super().structure(systeme, message, format_sortie)

    modele = Capricieux(_proposition(puces_0=[MENSONGE], puces_1=[
        "Gestion quotidienne d'un portefeuille de 15 à 25 entreprises (50 à 75 millions d'euros de chiffre d'affaires)."]))
    ciblage = cibler(_profil(), _offre(), {0: [RISQUE], 1: [PORTEFEUILLE]}, modele)
    assert ciblage.puces[0] == [RISQUE]
    assert "50 à 75 millions" in ciblage.puces[1][0] and ciblage.puces[1][0] != PORTEFEUILLE
    assert ciblage.journal["correction"] == "surcharge"


# --- L'ordre des puces --------------------------------------------------------


def test_les_puces_gardent_l_ordre_du_candidat_et_le_resultat_chiffre():
    """Sur le premier dossier réel, « trésorerie augmentée de 100 % » passait en
    dernier et « crowdfunding à 150 % » disparaissait : le recouvrement avec
    l'annonce ne voit pas qu'un résultat chiffré vaut plus qu'une tâche."""
    from app.documents.cv_render import _puces_ordonnees

    puces = ["Gestion de la trésorerie, augmentée de 100 % sur le mandat.",
             "Crowdfunding mené à 150 % de l'objectif fixé.",
             "Mise en place du compte de résultat.",
             "Gestion et négociation des partenariats.",
             "Appels d'offres sur contrats de prêt-à-porter."]
    gardees = _puces_ordonnees(puces, {"compte", "resultat", "partenariats"}, True, 3)
    assert "Crowdfunding mené à 150 % de l'objectif fixé." in gardees
    assert gardees == [p for p in puces if p in gardees], "l'ordre du profil doit être gardé"
