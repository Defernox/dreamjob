"""Application du score aux offres en base.

Le point clé : **changer les poids ne relance aucune extraction**. Les signaux
d'une offre (langue, vocabulaire, secteur) sont figés dans `Offer.extraction` et
ne dépendent que de l'offre ; seul le calcul, du code pur, est rejoué.
"""

from __future__ import annotations

import logging

from datetime import timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from ..config import reglages as lire_reglages
from ..models import Offer, Profile, ScoreOffre, Utilisateur
from ..models.base import maintenant
from ..scoring.explain import expliquer
from ..scoring.extraction import VERSION as VERSION_SIGNAUX
from ..scoring.extraction import signaux_de
from ..scoring.score import calculer

log = logging.getLogger("dreamjob.scoring")


class ProfilVide(RuntimeError):
    """Sans profil, un score n'aurait aucun sens."""


def profil_de(session: Session, utilisateur_id: int) -> Profile:
    """Le profil d'un compte. Créé vide au premier appel plutôt que renvoyer 404."""
    profil = session.exec(select(Profile).where(Profile.utilisateur_id == utilisateur_id)).first()
    if profil is None:
        profil = Profile(utilisateur_id=utilisateur_id)
        session.add(profil)
        session.commit()
        session.refresh(profil)
    return profil


def profil_courant(session: Session, utilisateur_id: int) -> Profile:
    """Le profil d'un compte, à condition qu'il permette de scorer."""
    profil = profil_de(session, utilisateur_id)
    if not (profil.skills or profil.secteurs):
        raise ProfilVide(
            "Le profil est vide : renseignez au moins vos compétences et vos "
            "secteurs dans l'onglet Profil avant de scorer des offres."
        )
    return profil


def scorer_offre(profil: Profile, offre: Offer, suivi: ScoreOffre, poids, version: int,
                 plafond_hors_cible: float = 100.0) -> ScoreOffre:
    """Note `offre` pour le profil. Les signaux, qui ne dépendent que de
    l'annonce, restent sur l'offre ; la note va dans `suivi`, propre au compte."""
    signaux = signaux_de(offre)
    resultat = calculer(profil, offre, signaux, poids, plafond_hors_cible)

    offre.extraction = signaux.en_dict()
    offre.extraction_modele = "lexical"      # aucun LLM : c'est le but

    suivi.score = resultat.score
    suivi.score_detail = resultat.detail
    suivi.score_explication = expliquer(resultat, profil, offre, signaux)
    suivi.scored_at = maintenant()
    suivi.poids_version = version
    suivi.version_signaux = VERSION_SIGNAUX
    return suivi


def scorer_toutes(session: Session, utilisateur_id: int, *, forcer: bool = False) -> dict:
    """Score ce qui doit l'être dans le fil d'un compte. Renvoie un petit compte rendu.

    Sans `forcer`, une offre déjà scorée avec la version de poids courante est
    laissée telle quelle.
    """
    reglages = lire_reglages()
    poids = reglages.scoring.poids
    version = reglages.scoring.version
    profil = profil_courant(session, utilisateur_id)

    requete = (select(Offer, ScoreOffre)
               .join(ScoreOffre, ScoreOffre.offer_id == Offer.id)
               .where(ScoreOffre.utilisateur_id == utilisateur_id))
    if not forcer:
        # `poids_version != version` est FAUX quand la colonne vaut NULL (règle
        # SQL sur les NULL) : sans le test explicite, une offre scorée avant
        # l'introduction du versionnage ne serait jamais rescorée.
        #
        # La version des *signaux* est un compteur distinct de celle des poids.
        # Sans ce second test, incrémenter `extraction.VERSION` ne servait à
        # rien : l'offre n'était pas revisitée, donc `signaux_de` n'était jamais
        # rappelé et les signaux périmés restaient en base. Il se lit sur la
        # NOTE et non sur l'offre : le premier compte qui rescore met à jour les
        # signaux de l'offre, les autres doivent quand même rescorer.
        # Le critère de fraîcheur dépend du jour : un score stocké vieillit.
        # On rescore donc ce qui date de plus d'un jour — l'opération prend une
        # seconde pour 2 490 offres, la fraîcheur peut bien la coûter.
        perime = maintenant() - timedelta(days=1)

        requete = requete.where(
            ScoreOffre.score.is_(None)
            | ScoreOffre.poids_version.is_(None)
            | (ScoreOffre.poids_version != version)
            | ScoreOffre.version_signaux.is_(None)
            | (ScoreOffre.version_signaux != VERSION_SIGNAUX)
            | ScoreOffre.scored_at.is_(None)
            | (ScoreOffre.scored_at < perime)
        )

    paires = list(session.exec(requete).all())
    for offre, suivi in paires:
        scorer_offre(profil, offre, suivi, poids, version, reglages.scoring.plafond_hors_cible)
        session.add(offre)
        session.add(suivi)
    session.commit()

    total = session.exec(select(func.count()).select_from(ScoreOffre)
                         .where(ScoreOffre.utilisateur_id == utilisateur_id)).one()
    log.info("Scoring : %d offres traitées sur %d", len(paires), total)
    return {
        "scorees": len(paires),
        "total": total,
        "version_poids": version,
        "appels_llm": 0,      # invariant : le scoring n'appelle jamais de LLM
    }


def scorer_tous_les_comptes(session: Session) -> int:
    """Rescore le fil de chaque compte dont le profil le permet. Renvoie le
    nombre d'offres notées ; un profil vide est passé sans erreur."""
    total = 0
    for utilisateur in session.exec(select(Utilisateur)).all():
        try:
            total += scorer_toutes(session, utilisateur.id)["scorees"]
        except ProfilVide:
            log.info("Compte %s : profil vide, offres non scorées.", utilisateur.id)
    return total
