"""Application du score aux offres en base.

Le point clé : **changer les poids ne relance aucune extraction**. Les signaux
d'une offre (intitulé, contenu, exigences, langue) sont figés dans
`Offer.extraction` et ne dépendent que de l'offre ; seul le calcul, du code pur,
est rejoué.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

from sqlmodel import Session, select

from ..config import reglages as lire_reglages
from ..models import Offer, Profile, Recherche, ScoreOffre, Utilisateur
from ..models.base import maintenant
from ..scoring.cible import ProfilCible, construire
from ..scoring.corpus import NEUTRE, Corpus
from ..scoring.explain import expliquer
from ..scoring.extraction import VERSION as VERSION_SIGNAUX
from ..scoring.extraction import Signaux, signaux_de
from ..scoring.score import calculer, etalonner

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


def recherches_de(session: Session, utilisateur_id: int) -> list[list[str]]:
    """Les mots-clés des recherches actives du compte : ce qu'il dit chercher."""
    return [list(r.mots_cles) for r in session.exec(
        select(Recherche).where(Recherche.utilisateur_id == utilisateur_id, Recherche.active)
    ).all()]


def preparer(session: Session, profil: Profile, paires: list[tuple[Offer, ScoreOffre]]
             ) -> tuple[ProfilCible, Corpus, dict[int, Signaux]]:
    """Ce que le score d'un compte demande une fois pour toutes ses offres : le
    profil de ciblage tiré de tout le CV, le corpus de son fil, et l'étalonnage
    du contenu sur ses meilleures offres."""
    signaux = {offre.id: signaux_de(offre) for offre, _ in paires}
    corpus = Corpus.depuis(signaux.values())
    cible = construire(profil, recherches_de(session, profil.utilisateur_id))
    etalonner(cible, list(signaux.values()), corpus)
    return cible, corpus, signaux


def scorer_offre(profil: Profile, offre: Offer, suivi: ScoreOffre, poids, version: int,
                 cible: ProfilCible, corpus: Corpus = NEUTRE,
                 signaux: Signaux | None = None) -> ScoreOffre:
    """Note `offre` pour le profil. Les signaux, qui ne dépendent que de
    l'annonce, restent sur l'offre ; la note va dans `suivi`, propre au compte."""
    signaux = signaux or signaux_de(offre)
    resultat = calculer(profil, offre, signaux, poids, cible, corpus)

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

    Le corpus et l'étalonnage portent sur TOUT le fil, même quand seules
    quelques offres sont à noter : une offre se juge par rapport aux autres.
    """
    reglages = lire_reglages()
    poids = reglages.scoring.poids
    version = reglages.scoring.version
    profil = profil_courant(session, utilisateur_id)

    toutes = list(session.exec(
        select(Offer, ScoreOffre)
        .join(ScoreOffre, ScoreOffre.offer_id == Offer.id)
        .where(ScoreOffre.utilisateur_id == utilisateur_id)).all())

    # `poids_version != version` est FAUX quand la colonne vaut NULL (règle SQL
    # sur les NULL) : d'où les tests explicites. La version des *signaux* se lit
    # sur la NOTE et non sur l'offre : le premier compte qui rescore met à jour
    # les signaux de l'offre, les autres doivent quand même rescorer. Et le
    # score vieillit (fraîcheur, corpus) : on rescore ce qui a plus d'un jour.
    perime = maintenant() - timedelta(days=1)
    a_noter = [
        (offre, suivi) for offre, suivi in toutes
        if forcer or suivi.score is None or suivi.poids_version != version
        or suivi.version_signaux != VERSION_SIGNAUX
        or suivi.scored_at is None or suivi.scored_at < perime
    ]
    if a_noter:
        cible, corpus, signaux = preparer(session, profil, toutes)
        for offre, suivi in a_noter:
            scorer_offre(profil, offre, suivi, poids, version, cible, corpus,
                         signaux[offre.id])
            session.add(offre)
            session.add(suivi)
        session.commit()

    log.info("Scoring : %d offres traitées sur %d", len(a_noter), len(toutes))
    return {
        "scorees": len(a_noter),
        "total": len(toutes),
        "version_poids": version,
        "appels_llm": 0,      # invariant : le scoring n'appelle jamais de LLM
    }


# Un recalcul à la fois par compte : deux enregistrements rapprochés du profil
# ne doivent pas lancer deux calculs qui s'écrasent — le second attend le
# premier, puis part du profil à jour.
_VERROUS: dict[int, threading.Lock] = {}
_VERROU_DES_VERROUS = threading.Lock()


def rescorer(moteur, utilisateur_id: int, *, forcer: bool = True) -> None:
    """Recalcule les notes d'un compte, hors de la requête qui l'a demandé.

    Le score lit tout le CV et toutes les recherches : sans ce recalcul, un
    profil modifié gardait ses anciennes notes jusqu'au lendemain. `moteur` est
    celui de la requête — jamais le moteur global, qui viserait la vraie base
    depuis un test. Ne lève jamais : un recalcul manqué sera rattrapé.
    """
    with _VERROU_DES_VERROUS:
        verrou = _VERROUS.setdefault(utilisateur_id, threading.Lock())
    with verrou:
        try:
            with Session(moteur) as session:
                scorer_toutes(session, utilisateur_id, forcer=forcer)
        except ProfilVide:
            pass
        except Exception:  # noqa: BLE001
            log.exception("Recalcul des notes du compte %s en échec", utilisateur_id)


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
