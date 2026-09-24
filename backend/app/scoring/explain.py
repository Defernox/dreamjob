"""L'explication d'un score, en quelques lignes.

Objectif : comprendre **pourquoi** une offre a ce score sans lire le code. Une
ligne par question — le métier, le contenu, le niveau, le diplôme, la langue,
les conditions — et les points rédhibitoires en tête. Des faits, avec les mots
de l'annonce et de votre CV, aucun jargon.
"""

from __future__ import annotations

import re

from ..models import Offer, Profile
from .extraction import Signaux
from .lexique import canon, jetons
from .score import (
    LOC_MEME_PAYS,
    LOC_MEME_VILLE,
    LOC_PAYS_ACCEPTE,
    Resultat,
    _niveau_du_profil,
)
from .texte import normaliser

MAX_TERMES = 6
_MOT = re.compile(r"[\w+#]+(?:[.'’-][\w+#]+)*", re.UNICODE)

LIBELLE_NIVEAU = {
    "stage": "un stage", "junior": "un poste junior",
    "intermediaire": "un poste de niveau intermédiaire",
    "confirme": "un poste senior", "encadrement": "un poste d'encadrement",
    "direction": "un poste de direction",
}


def _surfaces(texte: str) -> dict[str, str]:
    """Jeton canonique -> le mot tel qu'il est écrit, pour parler avec les mots
    de l'annonce plutôt qu'avec des racines (« solvabilité », pas « solvabilit »)."""
    table: dict[str, str] = {}
    for mot in _MOT.findall(texte or ""):
        for morceau in normaliser(mot).split():
            table.setdefault(canon(morceau), mot.lower())
    return table


def _mots(termes: list[str], surfaces: dict[str, str], exclus: set[str] = frozenset()) -> str:
    """Les termes, avec les mots de l'annonce. Les mots trop courts pour se lire
    seuls, et ceux de l'employeur ou du lieu, ne sont pas des exigences."""
    vus: list[str] = []
    for terme in termes:
        mot = surfaces.get(terme)
        if mot and len(mot) > 2 and terme not in exclus and mot not in vus:
            vus.append(mot)
        if len(vus) >= MAX_TERMES:
            break
    return ", ".join(vus)


def _ligne_metier(resultat: Resultat, surfaces: dict[str, str], exclus: set[str]) -> str:
    if "metier" in resultat.non_evaluables:
        return "Métier : non évalué (intitulé vide, ou aucun intitulé visé dans votre profil)."
    note = resultat.detail.get("metier", 0)
    if resultat.intitule_vise:
        texte = f"Métier : rejoint « {resultat.intitule_vise} » ({resultat.intitule_origine})"
    else:
        texte = "Métier : ne reprend aucun des intitulés que vous visez"
    inconnus = _mots(resultat.intitule_inconnus, surfaces, exclus)
    if inconnus and note < 85:
        texte += f" ; hors de votre CV : {inconnus}"
    return texte + "."


def _ligne_contenu(resultat: Resultat, surfaces: dict[str, str], exclus: set[str]) -> str:
    if "competences" in resultat.non_evaluables:
        return ""
    communs = _mots(resultat.cles_couvertes, surfaces, exclus)
    texte = f"En commun avec votre CV : {communs}." if communs else \
        "Presque rien en commun avec votre CV."
    absents = _mots(resultat.cles_manquantes, surfaces, exclus)
    if absents:
        texte += f" L'annonce insiste aussi sur : {absents}."
    return texte


def _ligne_niveau(resultat: Resultat, annees: int) -> str:
    if "seniorite" in resultat.non_evaluables:
        return ""
    note = resultat.detail.get("seniorite", 0)
    texte = f"Niveau : {LIBELLE_NIVEAU.get(resultat.niveau_poste, 'poste')}"
    if resultat.annees_exigees:
        texte += f", {resultat.annees_exigees} ans demandés pour vos {annees}"
    if note >= 90:
        return texte + " — à votre portée."
    if note >= 60:
        return texte + " — un cran au-dessus ou en dessous de votre parcours."
    return texte + " — nettement au-dessus de votre expérience."


def _ligne_formation(resultat: Resultat) -> str:
    if "formation" in resultat.non_evaluables or not resultat.etudes_demandees:
        return ""
    requis, plafond = resultat.etudes_demandees
    demande = f"Bac+{requis}" if requis == plafond else f"Bac+{requis} à Bac+{plafond}"
    note = resultat.detail.get("formation", 0)
    if note >= 100:
        return f"Diplôme : {demande} demandé — conforme."
    if note >= 55 and requis <= 3:
        return f"Diplôme : {demande} demandé — vous êtes au-dessus, le poste l'est peut-être moins."
    return f"Diplôme : {demande} demandé — au-dessus du vôtre."


def _langue_decisive(profil: Profile, signaux: Signaux) -> str:
    candidates = ([signaux.langue] if signaux.langue else []) + list(signaux.exigences_langues)
    if not candidates:
        return ""
    return min(candidates, key=lambda c: _niveau_du_profil(profil, c) or 0.0)


def _ligne_langue(resultat: Resultat, profil: Profile, signaux: Signaux) -> str:
    if "langue" in resultat.non_evaluables:
        return ""
    valeur = resultat.detail.get("langue", 0)
    code = _langue_decisive(profil, signaux)
    libelle = (code or "?").upper()
    if valeur >= 100:
        return f"Langue : {libelle}, maîtrisée."
    exigee = code and code != signaux.langue and code in signaux.exigences_langues
    if valeur > 0:
        return f"Langue : {libelle} {'exigé' if exigee else ''}, partiellement maîtrisé.".replace(" ,", ",")
    return f"Langue : {libelle} {'exigé' if exigee else ''}, non maîtrisé.".replace(" ,", ",")


def _fragment_lieu(resultat: Resultat, offre: Offer) -> str:
    if "pays" in resultat.non_evaluables:
        return ""
    valeur = resultat.detail.get("pays", 0)
    if valeur >= LOC_MEME_VILLE:
        return f"{offre.lieu or offre.pays}, votre ville"
    if valeur >= LOC_MEME_PAYS:
        return offre.lieu or offre.pays
    if valeur >= LOC_PAYS_ACCEPTE:
        return f"{offre.pays}, à l'étranger"
    return f"{offre.pays}, hors de vos pays"


def _fragment_contrat(resultat: Resultat, profil: Profile, offre: Offer) -> str:
    if "contrat" in resultat.non_evaluables:
        return ""
    contrat = offre.type_contrat or "?"
    if resultat.detail.get("contrat", 0) <= 0:
        return f"{contrat} non souhaité"
    rang = profil.contrats_acceptes.index(contrat) if contrat in profil.contrats_acceptes else 0
    # ASCII uniquement : cette ligne finit aussi dans l'export Excel.
    return f"{contrat} (votre 1er choix)" if rang == 0 else f"{contrat} ({rang + 1}e choix)"


def _fragment_fraicheur(resultat: Resultat) -> str:
    if "fraicheur" in resultat.non_evaluables:
        return ""
    valeur = resultat.detail.get("fraicheur", 0)
    if valeur >= 100:
        return "publiée cette semaine"
    if valeur >= 75:
        return "publiée ce mois-ci"
    if valeur >= 30:
        return "publiée il y a plus d'un mois"
    return "annonce ancienne, peut-être close" if valeur > 0 else "annonce probablement close"


def expliquer(resultat: Resultat, profil: Profile, offre: Offer, signaux: Signaux) -> str:
    """Une ligne par question, séparées par des retours à la ligne. Les
    critères non évalués ne sont pas énumérés."""
    surfaces = _surfaces(f"{offre.titre} {offre.description_brute}")
    exclus = set(jetons(f"{offre.entreprise} {offre.lieu} {offre.pays}"))
    conditions = ", ".join(filter(None, [
        _fragment_lieu(resultat, offre),
        _fragment_contrat(resultat, profil, offre),
        _fragment_fraicheur(resultat),
    ]))
    lignes = [
        ("Rédhibitoire : " + " ; ".join(resultat.redhibitoires) + ".")
        if resultat.redhibitoires else "",
        _ligne_metier(resultat, surfaces, exclus),
        _ligne_contenu(resultat, surfaces, exclus),
        _ligne_niveau(resultat, profil.annees_experience or 0),
        _ligne_formation(resultat),
        _ligne_langue(resultat, profil, signaux),
        f"Conditions : {conditions}." if conditions else "",
    ]
    return "\n".join(ligne for ligne in lignes if ligne)
