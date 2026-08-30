"""La lettre est écrite par le candidat, pas par le recruteur — et pas recopiée.

Deux contrôles qui s'ajoutent à l'anti-invention. Ils existent parce que le
premier laissait passer intactes les deux lettres les plus embarrassantes : une
lettre où le recruteur s'adresse au candidat, et une lettre qui répète l'annonce.
Dans les deux cas, aucun nom propre n'est inventé.
"""

import pytest

from app.documents.lettre import (
    LONGUEUR_COPIE,
    PROMPT_SYSTEME,
    copies_de_l_offre,
    rediger,
    voix_incorrecte,
)
from app.models import Offer, Profile

# Calquée sur ce que mistral:7b produisait avant correction du prompt. Les noms
# propres sont ceux des fixtures : le contrôle anti-invention ne doit PAS se
# déclencher ici, sinon il masquerait ce que ces tests vérifient.
LETTRE_INVERSEE = """Je suis heureuse de vous présenter une opportunité intéressante
dans le domaine de la finance. En effet, je recherche un candidat expérimenté
pour un poste chez Banque Exemple.

Votre profil correspond directement au poste visé. En tant que trésorier,
vous avez démontré votre capacité à gérer une trésorerie.

Je vous invite à envisager cette opportunité, un pas important dans votre carrière."""

LETTRE_CORRECTE = """Le poste que vous proposez correspond à ce que je cherche.
Mon parcours en finance m'a donné les bases du suivi des opérations.

Trésorier, j'ai suivi des créances export et mis en place un compte de résultat.
Votre équipe travaille sur des flux que je connais bien.

Ce poste m'intéresse pour la rigueur qu'il demande."""


@pytest.fixture
def profil():
    return Profile(
        prenom="Maxime", nom="Nicolas", ville="Paris", pays="France",
        titre_vise="Analyste financier",
        skills=[{"nom": "Analyse financière", "ancree": True}],
        langues=[{"code": "fr", "libelle": "Français", "niveau": "natif"}],
        experiences=[{"entreprise": "Crédit Mutuel", "poste": "Trésorier",
                      "debut": "2023-09", "fin": "2025-09",
                      "description": "Suivi des créances export."}],
        formations=[{"etablissement": "EM Normandie", "diplome": "Master 2 Finance",
                     "annee": "2020-2025"}],
    )


@pytest.fixture
def offre():
    return Offer(
        source="test", source_id="1", titre="Analyste risques de crédit",
        entreprise="Banque Exemple", lieu="Paris", pays="France", type_contrat="CDI",
        description_brute=(
            "Vous serez polyvalent sur tous les actes concernant l'assurance vie "
            "de manière générale, souscription, versements, arbitrages et rachats. "
            "Vous devrez faire preuve d'un fort niveau d'engagement et devenir "
            "rapidement opérationnel grâce à un accompagnement dédié."
        ),
    )


# --- La voix ----------------------------------------------------------------


def test_une_lettre_ecrite_par_le_recruteur_est_reconnue():
    fautes = voix_incorrecte(LETTRE_INVERSEE)
    assert "votre profil" in fautes
    assert "je recherche un candidat" in fautes


def test_une_lettre_du_candidat_passe():
    assert voix_incorrecte(LETTRE_CORRECTE) == []


def test_parler_de_l_entreprise_au_vous_reste_permis():
    """« votre équipe », « votre entreprise », « vos besoins » sont la raison
    d'être du vouvoiement : les interdire viderait la lettre."""
    texte = ("Je connais bien votre entreprise et vos besoins. Votre équipe "
             "travaille sur des sujets que j'ai déjà traités. Mon expérience "
             "m'a préparé à votre organisation.")
    assert voix_incorrecte(texte) == []


def test_une_lettre_sans_je_est_refusee():
    texte = ("Le poste correspond au parcours décrit. L'expérience acquise "
             "en trésorerie répond aux attentes exprimées dans l'annonce.")
    assert voix_incorrecte(texte)


# --- Le perroquet -----------------------------------------------------------


def test_une_phrase_recopiee_de_l_annonce_est_reconnue(offre):
    lettre = ("Je suis polyvalent sur tous les actes concernant l'assurance vie "
              "de manière générale, souscription, versements, arbitrages.")
    assert copies_de_l_offre(lettre, offre)


def test_reprendre_l_intitule_du_poste_reste_permis(offre):
    """Sinon on ne pourrait plus nommer le poste auquel on postule."""
    lettre = ("Le poste d'analyste risques de crédit correspond à mon parcours. "
              "J'ai suivi des créances à l'export pendant deux ans et mis en "
              "place un compte de résultat pour une association.")
    assert copies_de_l_offre(lettre, offre) == []


def test_une_offre_sans_description_ne_fait_rien_detecter(offre):
    offre.description_brute = ""
    assert copies_de_l_offre("Une lettre quelconque mais assez longue pour compter "
                             "au moins huit mots.", offre) == []


def test_le_seuil_laisse_passer_une_suite_plus_courte(offre):
    """Une reprise sous le seuil peut être une coïncidence, ou simplement la
    façon naturelle de nommer le poste. On découpe avec la même tokenisation
    que le contrôle : les apostrophes comptent pour des séparateurs."""
    from app.scoring.texte import mots

    debut = " ".join(mots(offre.description_brute, garder_vides=True)[:LONGUEUR_COPIE - 1])
    assert copies_de_l_offre(debut, offre) == []


def test_nommer_le_poste_reste_possible_avec_un_intitule_long(offre):
    """Mesuré : « au sein d'un Middle office Assurance H/F en CDI » fait dix
    jetons. À huit, le candidat ne pouvait plus dire où il postulait."""
    offre.description_brute = (
        "Au sein de la Direction Gestion des Contrats, vous intégrez le pôle "
        "Middle Office Assurance Vie en CDI."
    )
    lettre = ("Je postule au sein de votre pôle Middle Office Assurance Vie en CDI. "
              "Mon parcours en trésorerie m'a préparé au suivi des dossiers.")
    assert copies_de_l_offre(lettre, offre) == []


# --- Le prompt --------------------------------------------------------------


def test_le_prompt_impose_la_premiere_personne():
    """La consigne « Le vouvoiement, et rien d'autre » avait fait vouvoyer le
    CANDIDAT : le modèle s'est mis à la place du recruteur."""
    assert "première personne du singulier" in PROMPT_SYSTEME
    assert "Tu ES le candidat" in PROMPT_SYSTEME


# --- La boucle de correction ------------------------------------------------


def test_une_voix_inversee_declenche_une_regeneration(profil, offre):
    essais = []

    def generer(systeme, message):
        essais.append(systeme)
        return LETTRE_INVERSEE if len(essais) == 1 else _assez_longue(LETTRE_CORRECTE)

    lettre, compte_rendu = rediger(profil, offre, generer, tentatives=3)
    assert compte_rendu["essais"] == 2
    assert "mauvais côté" in essais[1]           # le reproche est nommé au modèle
    assert voix_incorrecte(lettre) == []


def test_une_lettre_toujours_inversee_est_refusee(profil, offre):
    with pytest.raises(ValueError, match="mauvais côté"):
        rediger(profil, offre, lambda s, m: LETTRE_INVERSEE, tentatives=2)


def test_une_copie_persistante_est_signalee_mais_livree(profil, offre):
    """Le perroquet ne distingue pas « j'ai fait X » de « je ferais X » : la
    seconde décrit le poste, et le prompt demande justement de nommer des
    éléments de l'annonce. Le rendre bloquant refusait deux offres réelles sur
    deux, sans produire le moindre document. On livre, on signale."""
    copie = _assez_longue(
        "Je serai polyvalent sur tous les actes concernant l'assurance vie de "
        "manière générale, souscription, versements, arbitrages et rachats."
    )
    lettre, compte_rendu = rediger(profil, offre, lambda s, m: copie, tentatives=2)
    assert lettre
    assert compte_rendu["style"]["copies"]


def _assez_longue(corps: str) -> str:
    """Complète un texte pour dépasser MOTS_MIN sans rien recopier de l'offre."""
    return corps + " " + ("Ce point me semble déterminant pour la suite. " * 20)


# --- Les formules creuses : défaut de style, pas de malhonnêteté -------------


def test_les_cliches_sont_reperes():
    from app.documents.lettre import cliches

    brouillon = ("Je suis prêt à relever les défis de ce poste et à apporter mes "
                 "talents pour atteindre des résultats exceptionnels.")
    trouves = cliches(brouillon)
    assert "relever les defis" in trouves
    assert "apporter mes talents" in trouves


def test_une_lettre_precise_ne_declenche_rien():
    from app.documents.lettre import cliches

    texte = ("Trésorier associatif, j'ai géré une trésorerie de 1 000 à 3 000 euros "
             "et mis en place un compte de résultat.")
    assert cliches(texte) == []


def test_une_lettre_honnete_mais_convenue_est_livree_avec_un_avertissement(profil, offre):
    """Refuser toute une lettre exacte pour « relever les défis » serait
    disproportionné : l'invention ment, le cliché ennuie. On livre et on prévient."""
    convenue = _assez_longue(
        "Le poste correspond à mon parcours. Je suis prêt à relever les défis "
        "que vous proposez, et mon expérience en trésorerie parle pour moi."
    )
    lettre, compte_rendu = rediger(profil, offre, lambda s, m: convenue, tentatives=2)
    assert "relever les defis" in compte_rendu["cliches"]
    assert lettre                      # la lettre est bien livrée


def test_une_lettre_malhonnete_reste_refusee(profil, offre):
    """La distinction ne doit pas devenir une porte de sortie : voix inversée,
    invention et recopie bloquent toujours."""
    with pytest.raises(ValueError):
        rediger(profil, offre, lambda s, m: _assez_longue(LETTRE_INVERSEE), tentatives=2)
