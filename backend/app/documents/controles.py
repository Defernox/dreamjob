"""Les contrôles d'une lettre de motivation.

Sortis de `lettre.py`, qui n'a plus à porter que les prompts et la boucle de
génération. Chaque fonction rend une **liste de reproches** : vide si la lettre
passe, sinon les fautes, formulées pour être renvoyées telles quelles au modèle.

**Deux familles, et la distinction commande tout le reste.**

| Famille | Contrôles | Effet |
|---|---|---|
| honnêteté | invention, chiffres, voix, contrat | **bloquant** |
| style | perroquet, disponibilité, formules creuses, ouverture, rythme | signalé |

**Pourquoi le perroquet n'est pas bloquant.** Il ne sait pas distinguer « j'ai
réalisé des travaux de backtesting » — un mensonge — de « je serais amené à
réaliser des travaux de backtesting », qui décrit simplement le poste. Or le
prompt DEMANDE de citer des éléments de l'annonce : le rendre bloquant revenait
à exiger une chose et à la punir. Mesuré : deux offres sur deux refusées après
quatre essais, aucun document produit. Les vraies inventions sont attrapées par
les contrôles de noms propres et de chiffres, qui, eux, ne se trompent pas.

Les premiers rendent la lettre *fausse* : elle affirme quelque chose d'inexact
sur le candidat, et mieux vaut pas de lettre du tout. Les seconds la rendent
seulement *convenue* : on livre, on nomme, l'utilisateur retouche. Confondre les
deux menait à refuser des lettres exactes pour un « relever les défis » — mesuré
sur mistral:7b, qui échouait alors quatre fois d'affilée sans jamais produire de
document.
"""

from __future__ import annotations

import re

from ..models import Offer, Profile
from ..scoring.texte import mots, normaliser

# --- Vocabulaire de référence ------------------------------------------------

# Mots qui portent une majuscule sans être des noms propres à vérifier.
COURANTS = {
    "je", "j", "vous", "votre", "vos", "nous", "notre", "nos", "madame", "monsieur",
    "mesdames", "messieurs", "cordialement", "objet", "candidature", "lettre",
    "le", "la", "les", "un", "une", "ce", "cette", "mon", "ma", "mes", "au", "aux",
    "en", "dans", "pour", "avec", "sur", "par", "depuis", "apres", "avant", "enfin",
    "aujourd", "hui", "actuellement", "ainsi", "cependant", "toutefois",
    "titulaire", "diplome", "master", "licence", "bachelor", "bac", "mba", "bts", "dut",
    "janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout",
    "septembre", "octobre", "novembre", "decembre",
    "cdi", "cdd", "stage", "alternance", "interim", "vie", "france", "europe",
    "anglais", "francais", "allemand", "espagnol", "italien",
}

_DEBUT_PHRASE = re.compile(r"(?:^|[.!?:;]\s+|\n\s*)$")
_MOT_CAPITALISE = re.compile(r"\b[A-ZÀ-Þ][\wÀ-ÿ'’.-]{2,}")
_ANNEE = re.compile(r"\b(?:19|20)\d{2}\b")


def sources_texte(profil: Profile, offre: Offer) -> list[str]:
    """Tout ce que le candidat et l'offre mentionnent réellement."""
    morceaux: list[str] = [
        profil.prenom, profil.nom, profil.ville, profil.pays, profil.titre_vise,
        profil.resume, profil.situation_actuelle, profil.disponibilite,
        offre.titre, offre.entreprise, offre.lieu, offre.pays,
        offre.description_brute,
    ]
    morceaux += profil.secteurs
    morceaux += [s.get("nom", "") for s in profil.skills]
    morceaux += [lg.get("libelle", "") for lg in profil.langues]
    for experience in profil.experiences:
        morceaux += [experience.get("entreprise", ""), experience.get("poste", ""),
                     experience.get("lieu", ""), experience.get("description", ""),
                     experience.get("debut", ""), experience.get("fin", "")]
        morceaux += experience.get("tags", [])
    for formation in profil.formations:
        morceaux += [formation.get("etablissement", ""), formation.get("diplome", ""),
                     formation.get("lieu", ""), formation.get("details", ""),
                     formation.get("annee", "")]
    return [m for m in morceaux if m]


def _vocabulaire_autorise(profil: Profile, offre: Offer) -> set[str]:
    autorise = set(COURANTS)
    for morceau in sources_texte(profil, offre):
        autorise.update(normaliser(morceau).split())
    return autorise


# --- 1. Invention de noms propres --------------------------------------------


def entites_suspectes(lettre: str, profil: Profile, offre: Offer) -> list[str]:
    """Noms propres et années de la lettre absents du profil et de l'offre.

    Les mots en début de phrase sont ignorés : leur majuscule y est
    grammaticale, pas significative.
    """
    autorise = _vocabulaire_autorise(profil, offre)
    suspects: list[str] = []

    for correspondance in _MOT_CAPITALISE.finditer(lettre):
        if _DEBUT_PHRASE.search(lettre[:correspondance.start()]):
            continue
        mot = correspondance.group()
        # `mots()` retire la ponctuation de bord : « Exemple. » doit être reconnu
        # comme « Exemple », sinon toute fin de phrase devient suspecte.
        jetons = mots(mot) or [normaliser(mot)]
        if all(j in autorise for j in jetons):
            continue
        if mot not in suspects:
            suspects.append(mot)

    # Les dates aussi s'inventent : un modèle annonce volontiers une
    # disponibilité que le candidat n'a jamais donnée.
    annees_connues = {a.group() for morceau in sources_texte(profil, offre)
                      for a in _ANNEE.finditer(morceau)}
    for annee in _ANNEE.finditer(lettre):
        if annee.group() not in annees_connues and annee.group() not in suspects:
            suspects.append(annee.group())

    return suspects


# --- 2. Invention de chiffres ------------------------------------------------
# Un modèle qui n'a pas de chiffre sous la main en fabrique un plausible : « un
# portefeuille de 40 clients », « une équipe de 12 personnes ». Le contrôle des
# noms propres ne voyait que les années.

# « 50 000 » et « 50000 » sont le même nombre ; « 16,75 » et « 16.75 » aussi.
# Sans cette normalisation, une lettre qui espace ses milliers — ce que fait la
# typographie française — verrait tous ses chiffres portés disparus.
_ESPACE_DANS_NOMBRE = re.compile(r"(?<=\d)[\s  ](?=\d)")
_NOMBRE = re.compile(r"\d+(?:[.,]\d+)?")


def _nombres(texte: str) -> set[str]:
    nu = _ESPACE_DANS_NOMBRE.sub("", texte or "")
    return {n.replace(",", ".").rstrip(".") for n in _NOMBRE.findall(nu)}


def chiffres_inventes(lettre: str, profil: Profile, offre: Offer) -> list[str]:
    """Nombres de la lettre absents du profil et de l'offre.

    Les années sont laissées à `entites_suspectes`, qui les traite déjà : les
    signaler deux fois embrouillerait le reproche fait au modèle.
    """
    connus: set[str] = set()
    for morceau in sources_texte(profil, offre):
        connus |= _nombres(morceau)

    inventes = []
    for nombre in sorted(_nombres(lettre) - connus):
        if _ANNEE.fullmatch(nombre):
            continue
        inventes.append(nombre)
    return inventes


# --- 3. La voix de la lettre -------------------------------------------------
# Un modèle local se met volontiers à la place du recruteur et propose le poste
# au candidat (« Votre profil correspond… », « je recherche un candidat
# expérimenté »). La lettre reste pourtant *vraie* — tous les noms propres
# viennent du profil — donc le contrôle anti-invention la laisse passer.

_MARQUES_PREMIERE_PERSONNE = {"je", "j", "mon", "ma", "mes", "moi"}

# Tournures qui ne peuvent désigner que le candidat : les rencontrer au « vous »
# signifie que la lettre lui est adressée au lieu d'être écrite par lui.
# « votre entreprise », « votre équipe », « vos besoins » sont parfaitement
# légitimes et n'ont rien à faire dans cette liste.
_TOURNURES_INVERSEES = (
    "votre profil", "votre candidature", "votre cv", "votre curriculum",
    "votre parcours", "votre carriere", "votre formation", "votre diplome",
    "vous avez demontre", "vous avez acquis", "vous avez occupe",
    "vous avez travaille", "vous disposez d",
    "je recherche un candidat", "nous recherchons un candidat",
    "je vous propose ce poste", "votre capacite a",
)


def voix_incorrecte(lettre: str) -> list[str]:
    """Signes que la lettre n'est pas écrite par le candidat lui-même."""
    nu = normaliser(lettre)
    fautes = [t for t in _TOURNURES_INVERSEES if t in nu]
    if not _MARQUES_PREMIERE_PERSONNE & set(nu.split()):
        fautes.append("aucune marque de première personne (« je », « mon »)")
    return fautes


# --- 4. Le perroquet ---------------------------------------------------------
# À court de matière, le modèle recopie les exigences de l'annonce et les
# présente comme le parcours du candidat. Rien n'est « inventé » — les mots
# viennent de l'offre — mais le candidat s'attribue des compétences qu'il n'a
# pas, et le recruteur reconnaît son propre texte.
#
# Le seuil est un compromis, mesuré sur des lettres réelles :
#
#   « au sein d'un Middle office Assurance H/F en CDI »            10 jetons
#   « à l'aise à l'oral, notamment au téléphone, que par écrit »   11 jetons
#   « la conformité et la complétude des actes de gestion… »       14 jetons
#   « polyvalent sur tous les actes concernant l'assurance vie… »  15 jetons
#
# Les deux premières sont légitimes — on doit pouvoir nommer le poste auquel on
# postule — les deux dernières sont de vraies recopies. À huit jetons, tout
# était refusé et mistral n'arrivait jamais au bout de ses essais.
LONGUEUR_COPIE = 12


def _suites(jetons: list[str], longueur: int) -> set[tuple[str, ...]]:
    return {tuple(jetons[i:i + longueur]) for i in range(len(jetons) - longueur + 1)}


def copies_de_l_offre(lettre: str, offre: Offer) -> list[str]:
    """Passages recopiés mot pour mot depuis l'annonce."""
    de_la_lettre = mots(lettre, garder_vides=True)
    de_l_offre = mots(offre.description_brute or "", garder_vides=True)
    if len(de_la_lettre) < LONGUEUR_COPIE or len(de_l_offre) < LONGUEUR_COPIE:
        return []
    communes = (_suites(de_la_lettre, LONGUEUR_COPIE)
                & _suites(de_l_offre, LONGUEUR_COPIE))
    # Trois exemples suffisent à faire comprendre le reproche au modèle.
    return [" ".join(suite) for suite in sorted(communes)][:3]


# --- 5. Le type de contrat ---------------------------------------------------
# Mesuré : mistral écrit « alternance » sur une offre en CDI. Une lettre qui se
# trompe de contrat est écartée à la lecture, avant même le fond.

_CONTRATS_INCOMPATIBLES = {
    "CDI": ("alternance", "apprentissage", "stage", "stagiaire", "interim"),
    "CDD": ("alternance", "apprentissage", "stage", "stagiaire"),
    "Stage": ("cdi", "alternance", "apprentissage"),
    "Alternance": ("cdi", "stage", "stagiaire"),
    "V.I.E": ("cdi", "alternance", "apprentissage", "stage"),
    "Intérim": ("cdi", "alternance", "apprentissage", "stage"),
}


def contrat_incoherent(lettre: str, profil: Profile, offre: Offer) -> list[str]:
    """Mentions d'un contrat que l'offre ne propose pas.

    Un mot présent dans le parcours du candidat est laissé passer : « durant mon
    stage chez X » reste vrai même si l'offre porte sur un CDI.
    """
    interdits = _CONTRATS_INCOMPATIBLES.get(offre.type_contrat or "", ())
    if not interdits:
        return []

    du_profil = normaliser(" ".join(
        [e.get("poste", "") + " " + e.get("description", "") for e in profil.experiences]
        + [f.get("diplome", "") + " " + f.get("details", "") for f in profil.formations]
    ))
    nu = normaliser(lettre)
    return [mot for mot in interdits if mot in nu and mot not in du_profil]


# --- 6. La disponibilité ------------------------------------------------------
# Mesuré : le profil ne renseigne aucune disponibilité, le prompt le dit
# explicitement, et mistral écrit quand même « Je suis disponible
# immédiatement ». C'est une promesse au recruteur que le candidat n'a jamais
# faite — une invention, au même titre qu'un diplôme.

# Seules les promesses de DATE sont retenues. « Je suis disponible pour en
# discuter » est une clôture normale, pas un engagement : l'inclure faisait
# rejeter toutes les lettres, mistral la produisant systématiquement.
_ANNONCES_DISPONIBILITE = (
    "disponible immediatement", "disponibilite immediate",
    "disponible des", "libre immediatement",
    "a compter du", "a partir du", "sous preavis", "preavis de",
)


def disponibilite_inventee(lettre: str, profil: Profile) -> list[str]:
    """Disponibilité annoncée alors que le profil n'en donne aucune."""
    if (profil.disponibilite or "").strip():
        return []
    nu = normaliser(lettre)
    return [a for a in _ANNONCES_DISPONIBILITE if a in nu]


# --- 7. Les formules creuses -------------------------------------------------
# On a d'abord demandé au modèle de relire son propre brouillon et d'en retirer
# les clichés. Mesuré : mistral:7b en conserve la totalité — il ne sait pas
# s'auto-critiquer. Il obéit en revanche très bien quand on lui NOMME la faute,
# comme pour la voix et le perroquet. D'où cette liste, en pur code.
#
# Chaque entrée resterait vraie dans n'importe quelle lettre, pour n'importe
# quel poste. C'est le seul critère d'admission : une liste plus large ferait
# refuser des tournures légitimes.
_CLICHES = (
    # Ouvertures et transitions vides
    "fort de mon experience", "fort de mes experiences",
    "c est avec grand interet", "c est avec un vif interet",
    "c est tout naturellement que", "je me permets de vous adresser",
    # Auto-évaluation
    "dynamique et motive", "rigoureux et motive", "serieux autonomie",
    "particulierement motive", "vivement interesse",
    "esprit d equipe", "force de proposition", "polyvalent", "a l ecoute",
    "je suis convaincu", "je suis persuade",
    "je suis convaincu que mon profil", "correspond parfaitement a",
    # Promesses creuses
    "relever de nouveaux defis", "relever les defis", "relever ce defi",
    "mener a bien", "un reel atout", "un atout majeur",
    "apporter mes talents", "ma devotion",
    "resultats exceptionnels", "resultats remarquables",
    "mettre en pratique mes competences", "mes connaissances theoriques",
    # Flatterie de l'entreprise
    "environnement stimulant", "environnement dynamique",
    "entreprise en pleine croissance", "a la pointe de",
    "leader dans son domaine", "acteur incontournable",
    "reconnu pour son expertise", "groupe de reference",
    # Clôtures vides
    "formidable occasion", "formidable opportunite",
    "je serais ravi", "je serais enchante",
    "n hesitez pas a me contacter", "n hesitez pas a",
    "j attends avec impatience", "j attends donc avec impatience",
    "depuis toujours passionne", "passionne depuis toujours",
    "contribuer a la reussite de votre entreprise",
)


def cliches(lettre: str) -> list[str]:
    """Formules creuses repérées dans la lettre."""
    nu = normaliser(lettre)
    return [c for c in _CLICHES if c in nu]


# --- 8. L'ouverture ----------------------------------------------------------
# Les cinq façons de commencer une lettre qui annoncent au recruteur qu'il en a
# déjà lu trois cents identiques.

_OUVERTURES_INTERDITES = (
    "c est avec", "actuellement", "fort de", "passionne par", "suite a",
    "je me permets", "veuillez trouver",
)


def ouverture_convenue(lettre: str) -> list[str]:
    """La lettre commence-t-elle par une formule d'amorçage vide ?"""
    debut = normaliser(lettre)
    return [o for o in _OUVERTURES_INTERDITES if debut.startswith(o)]


# --- 9. Le rythme ------------------------------------------------------------
# Des phrases toutes de la même longueur se lisent comme un formulaire rempli.
# Une phrase courte par paragraphe suffit à casser la régularité.

PHRASE_COURTE_MAX = 12
_FIN_DE_PHRASE = re.compile(r"(?<=[.!?])\s+")


def rythme_mecanique(lettre: str) -> list[str]:
    """Paragraphes sans aucune phrase courte."""
    fautes = []
    paragraphes = [p for p in lettre.split("\n\n") if p.strip()]
    for numero, paragraphe in enumerate(paragraphes, start=1):
        phrases = [p for p in _FIN_DE_PHRASE.split(paragraphe) if p.strip()]
        if not phrases:
            continue
        if all(len(p.split()) > PHRASE_COURTE_MAX for p in phrases):
            fautes.append(f"paragraphe {numero} : aucune phrase de moins de "
                          f"{PHRASE_COURTE_MAX} mots")
    return fautes


# --- Synthèse ----------------------------------------------------------------


def bloquantes(lettre: str, profil: Profile, offre: Offer) -> dict[str, list[str]]:
    """Les fautes qui rendent la lettre fausse. Une seule suffit à la refuser."""
    return {
        "inventions": entites_suspectes(lettre, profil, offre),
        "chiffres": chiffres_inventes(lettre, profil, offre),
        "voix": voix_incorrecte(lettre),
        "contrat": contrat_incoherent(lettre, profil, offre),
    }


def defauts_de_style(lettre: str, profil: Profile,
                     offre: Offer) -> dict[str, list[str]]:
    """Les fautes qui la rendent seulement convenue. Signalées, jamais fatales."""
    return {
        "copies": copies_de_l_offre(lettre, offre),
        "disponibilite": disponibilite_inventee(lettre, profil),
        "cliches": cliches(lettre),
        "ouverture": ouverture_convenue(lettre),
        "rythme": rythme_mecanique(lettre),
    }
