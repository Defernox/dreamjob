"""Application du score aux offres en base.

Le point clé : **changer les poids ne relance aucune extraction**. Les signaux
d'une offre (langue, vocabulaire, secteur) sont figés dans `Offer.extraction` et
ne dépendent que de l'offre ; seul le calcul, du code pur, est rejoué.
"""

from __future__ import annotations

import logging

from sqlalchemy import func
from sqlmodel import Session, select

from ..config import reglages as lire_reglages
from ..models import Offer, Profile
from ..models.base import maintenant
from ..scoring.explain import expliquer
from ..scoring.extraction import VERSION as VERSION_SIGNAUX
from ..scoring.extraction import signaux_de
from ..scoring.score import calculer

log = logging.getLogger("dreamjob.scoring")


class ProfilVide(RuntimeError):
    """Sans profil, un score n'aurait aucun sens."""


def profil_courant(session: Session) -> Profile:
    profil = session.exec(select(Profile).order_by(Profile.id)).first()
    if profil is None or not (profil.skills or profil.secteurs):
        raise ProfilVide(
            "Le profil est vide : renseignez au moins vos compétences et vos "
            "secteurs dans l'onglet Profil avant de scorer des offres."
        )
    return profil


def scorer_offre(profil: Profile, offre: Offer, poids, version: int,
                 plafond_hors_cible: float = 100.0) -> Offer:
    signaux = signaux_de(offre)
    resultat = calculer(profil, offre, signaux, poids, plafond_hors_cible)

    offre.score = resultat.score
    offre.score_detail = resultat.detail
    offre.score_explication = expliquer(resultat, profil, offre, signaux)
    offre.extraction = signaux.en_dict()
    offre.extraction_modele = "lexical"      # aucun LLM : c'est le but
    offre.scored_at = maintenant()
    offre.poids_version = version
    return offre


def scorer_toutes(session: Session, *, forcer: bool = False) -> dict:
    """Score ce qui doit l'être. Renvoie un petit compte rendu.

    Sans `forcer`, une offre déjà scorée avec la version de poids courante est
    laissée telle quelle.
    """
    reglages = lire_reglages()
    poids = reglages.scoring.poids
    version = reglages.scoring.version
    profil = profil_courant(session)

    requete = select(Offer)
    if not forcer:
        # `poids_version != version` est FAUX quand la colonne vaut NULL (règle
        # SQL sur les NULL) : sans le test explicite, une offre scorée avant
        # l'introduction du versionnage ne serait jamais rescorée.
        #
        # La version des *signaux* est un compteur distinct de celle des poids.
        # Sans ce second test, incrémenter `extraction.VERSION` ne servait à
        # rien : l'offre n'était pas revisitée, donc `signaux_de` n'était jamais
        # rappelé et les signaux périmés restaient en base. `is_(None)` couvre à
        # la fois une colonne vide et un dictionnaire sans clé `version`.
        version_signaux = func.json_extract(Offer.extraction, "$.version")
        requete = requete.where(
            Offer.score.is_(None)
            | Offer.poids_version.is_(None)
            | (Offer.poids_version != version)
            | version_signaux.is_(None)
            | (version_signaux != VERSION_SIGNAUX)
        )

    offres = list(session.exec(requete).all())
    for offre in offres:
        session.add(scorer_offre(profil, offre, poids, version,
                                 reglages.scoring.plafond_hors_cible))
    session.commit()

    total = session.exec(select(Offer)).all()
    log.info("Scoring : %d offres traitées sur %d", len(offres), len(total))
    return {
        "scorees": len(offres),
        "total": len(total),
        "version_poids": version,
        "appels_llm": 0,      # invariant : le scoring n'appelle jamais de LLM
    }
