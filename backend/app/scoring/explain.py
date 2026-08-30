"""La ligne d'explication d'un score.

Objectif : comprendre **pourquoi** une offre a ce score sans lire le code ni
ouvrir le détail. Une phrase, des faits, aucun jargon.
"""

from __future__ import annotations

from ..models import Offer, Profile
from .extraction import Signaux
from .score import (
    LOC_MEME_PAYS,
    LOC_MEME_VILLE,
    LOC_PAYS_ACCEPTE,
    Resultat,
    _niveau_du_profil,
)

SEPARATEUR = " · "
MAX_SKILLS_CITEES = 4


def _fragment_secteur(resultat: Resultat) -> str:
    if "secteur" in resultat.non_evaluables:
        return "secteur non évalué"
    if resultat.detail.get("secteur", 0) <= 0:
        return "secteur hors cible"
    return f"secteur {resultat.secteur_reconnu}"


def _fragment_competences(resultat: Resultat) -> str:
    if "competences" in resultat.non_evaluables:
        return "compétences non évaluées"

    if resultat.ancrees_trouvees:
        citees = resultat.ancrees_trouvees[:MAX_SKILLS_CITEES]
        reste = len(resultat.ancrees_trouvees) - len(citees)
        texte = f"skills ancrées : {', '.join(citees)}"
        if reste:
            texte += f" (+{reste})"
    elif resultat.ancrees_manquantes:
        texte = "aucune skill ancrée"
    else:
        texte = "aucune skill ancrée définie"

    if resultat.autres_trouvees:
        texte += f" · {len(resultat.autres_trouvees)} autres skills"
    return texte


def _fragment_pays(resultat: Resultat, offre: Offer) -> str:
    """Le lieu compte quatre paliers depuis qu'il n'est plus binaire : dire
    seulement « pays OK » ferait passer un poste à São Paulo pour un poste à
    côté de chez soi."""
    if "pays" in resultat.non_evaluables:
        return "pays non évalué"
    valeur = resultat.detail.get("pays", 0)
    if valeur >= LOC_MEME_VILLE:
        return f"{offre.lieu or offre.pays} — votre ville"
    if valeur >= LOC_MEME_PAYS:
        return f"pays OK ({offre.pays})"
    if valeur >= LOC_PAYS_ACCEPTE:
        return f"{offre.pays} — accepté, mais à l'étranger"
    return f"pays hors liste ({offre.pays})"


def _langue_decisive(profil: Profile, signaux: Signaux) -> str:
    """La langue qui a fixé la note : c'est l'exigence la plus dure qui décide.

    En cas d'égalité, la langue de rédaction l'emporte — elle vient en tête.
    """
    candidates = ([signaux.langue] if signaux.langue else []) + list(signaux.exigences_langues)
    if not candidates:
        return ""
    return min(candidates, key=lambda c: _niveau_du_profil(profil, c) or 0.0)


def _fragment_langue(resultat: Resultat, profil: Profile, signaux: Signaux) -> str:
    if "langue" in resultat.non_evaluables:
        return "langue non évaluée"

    valeur = resultat.detail.get("langue", 0)
    # La note peut venir d'une langue **exigée** par l'annonce et non de celle
    # dans laquelle elle est rédigée. Nommer systématiquement la seconde
    # annonçait « langue FR non maîtrisée » à un francophone natif devant une
    # offre en français réclamant un anglais courant.
    code = _langue_decisive(profil, signaux)
    libelle = (code or "?").upper()

    if valeur >= 100:
        return f"langue {libelle} OK"
    if code and code != signaux.langue and code in signaux.exigences_langues:
        return (f"{libelle} exigé, partiellement maîtrisé" if valeur > 0
                else f"{libelle} exigé, non maîtrisé")
    if valeur > 0:
        return f"langue {libelle} partielle"
    return f"langue {libelle} non maîtrisée"


def _fragment_contrat(resultat: Resultat, profil: Profile, offre: Offer) -> str:
    if "contrat" in resultat.non_evaluables:
        return "contrat non évalué"
    contrat = offre.type_contrat or "?"
    if resultat.detail.get("contrat", 0) <= 0:
        return f"{contrat} non souhaité"
    rang = profil.contrats_acceptes.index(contrat) if contrat in profil.contrats_acceptes else 0
    if rang == 0:
        return f"{contrat} prioritaire"
    # ASCII uniquement : cette ligne finit aussi dans l'export Excel.
    return f"{contrat} accepté ({rang + 1}e choix)"


def expliquer(resultat: Resultat, profil: Profile, offre: Offer, signaux: Signaux) -> str:
    if resultat.hors_cible:
        return SEPARATEUR.join([
            "HORS CIBLE : ni compétences ni secteur ne correspondent",
            _fragment_pays(resultat, offre),
            _fragment_contrat(resultat, profil, offre),
        ])
    return SEPARATEUR.join([
        _fragment_secteur(resultat),
        _fragment_competences(resultat),
        _fragment_pays(resultat, offre),
        _fragment_langue(resultat, profil, signaux),
        _fragment_contrat(resultat, profil, offre),
    ])
