"""Les offres : liste filtrée, détail, et déclenchement du scoring."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from ..db import get_session
from ..config import reglages
from ..models import Application, Offer, ScoreOffre, Utilisateur
from ..models.base import maintenant
from ..schemas.offre import (
    Compteurs,
    OffreDetail,
    OffreResume,
    PageOffres,
    ResultatScoring,
    Statistiques,
)
from ..services.scan import dernier_scan_abouti
from ..services.scoring import ProfilVide, scorer_toutes
from .acces import utilisateur_courant

router = APIRouter(prefix="/api/offres", tags=["offres"])

# Chaque requête part du fil du compte : une jointure INTERNE sur ses notes.
# Une offre qu'aucune de ses recherches n'a ramenée n'existe pas pour lui — ni
# dans la liste, ni par son identifiant.


def _fil(utilisateur_id: int):
    return (ScoreOffre.offer_id == Offer.id) & (ScoreOffre.utilisateur_id == utilisateur_id)


def suivi_de(session: Session, offre_id: int, utilisateur_id: int) -> tuple[Offer, ScoreOffre]:
    """L'offre et la note du compte, ou 404 si elle n'est pas dans son fil."""
    offre = session.get(Offer, offre_id)
    suivi = session.get(ScoreOffre, (utilisateur_id, offre_id)) if offre else None
    if offre is None or suivi is None:
        raise HTTPException(404, "Offre introuvable.")
    return offre, suivi


def fusion(offre: Offer, suivi: ScoreOffre) -> dict:
    """L'offre telle que l'API l'a toujours servie : ses champs, plus la note et
    l'état « vue » de CE compte."""
    return offre.model_dump() | {
        "score": suivi.score, "score_detail": suivi.score_detail,
        "score_explication": suivi.score_explication, "scored_at": suivi.scored_at,
        "poids_version": suivi.poids_version, "vue": suivi.vue,
    }

def echapper_like(terme: str) -> str:
    """Neutralise les jokers de LIKE dans une saisie utilisateur.

    Sans cela, taper « % » remonte les 448 offres et « middle_office » match
    n'importe quel caractère à la place du souligné : la recherche ment
    silencieusement sur ce qu'elle a trouvé.
    """
    return terme.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")


TRIS = {
    # « Pertinence » : le meilleur score d'abord, la plus fraîche pour départager.
    "pertinence": (ScoreOffre.score.desc().nulls_last(),
                   Offer.date_publication.desc().nulls_last()),
    "score": (ScoreOffre.score.desc().nulls_last(),),
    "recentes": (Offer.date_publication.desc().nulls_last(),),
    "anciennes": (Offer.date_publication.asc().nulls_last(),),
}


def _filtres(contrats, sources, pays, score_min, recherche, *, sauf: str = "") -> list:
    """Conditions SQL. `sauf` retire une facette, pour compter ses propres options."""
    conditions = []
    if contrats and sauf != "contrat":
        conditions.append(Offer.type_contrat.in_(contrats))
    if sources and sauf != "source":
        conditions.append(Offer.source.in_(sources))
    if pays and sauf != "pays":
        conditions.append(Offer.pays.in_(pays))
    if score_min is not None:
        conditions.append(ScoreOffre.score >= score_min)
    if recherche:
        motif = f"%{echapper_like(recherche)}%"
        conditions.append(
            Offer.titre.ilike(motif, escape="\\")
            | Offer.entreprise.ilike(motif, escape="\\")
            | Offer.description_brute.ilike(motif, escape="\\")
        )
    return conditions


def _seuil_expiration() -> datetime:
    """Une offre revue avant cette date est considérée retirée du site."""
    return maintenant() - timedelta(days=reglages().offres.expiree_apres_jours)


def _compter(session: Session, colonne, conditions, utilisateur_id: int) -> dict[str, int]:
    requete = (select(colonne, func.count()).select_from(Offer)
               .join(ScoreOffre, _fil(utilisateur_id)).group_by(colonne))
    for condition in conditions:
        requete = requete.where(condition)
    return {valeur: nombre for valeur, nombre in session.exec(requete).all() if valeur}


@router.get("", response_model=PageOffres)
def lister(
    contrats: list[str] | None = Query(None),
    sources: list[str] | None = Query(None),
    pays: list[str] | None = Query(None),
    score_min: float | None = Query(None, ge=0, le=100),
    recherche: str | None = None,
    # None = toutes ; False = seulement les offres encore en ligne.
    expirees: bool | None = None,
    tri: str = "pertinence",
    # 500 : de quoi tout afficher sur une base locale, sans permettre de
    # demander un volume qui ferait ramer l'interface.
    limite: int = Query(60, ge=1, le=500),
    decalage: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    moi: Utilisateur = Depends(utilisateur_courant),
) -> PageOffres:
    if tri not in TRIS:
        raise HTTPException(400, f"Tri inconnu. Valeurs possibles : {', '.join(TRIS)}")

    conditions = _filtres(contrats, sources, pays, score_min, recherche)
    if expirees is not None:
        seuil = _seuil_expiration()
        conditions.append(
            Offer.derniere_vue_le < seuil if expirees else Offer.derniere_vue_le >= seuil
        )

    requete = select(Offer, ScoreOffre).join(ScoreOffre, _fil(moi.id))
    for condition in conditions:
        requete = requete.where(condition)
    total = session.exec(
        select(func.count()).select_from(Offer).join(ScoreOffre, _fil(moi.id)).where(*conditions)
    ).one()

    paires = list(session.exec(
        requete.order_by(*TRIS[tri]).offset(decalage).limit(limite)
    ).all())

    candidatures = set(session.exec(
        select(Application.offer_id).where(Application.utilisateur_id == moi.id)).all())
    seuil = _seuil_expiration()

    return PageOffres(
        total=total,
        offres=[
            OffreResume(**fusion(o, s), a_candidature=o.id in candidatures,
                        expiree=o.derniere_vue_le < seuil)
            for o, s in paires
        ],
        compteurs=Compteurs(
            contrat=_compter(session, Offer.type_contrat,
                             _filtres(contrats, sources, pays, score_min, recherche,
                                      sauf="contrat"),
                             moi.id),
            source=_compter(session, Offer.source,
                            _filtres(contrats, sources, pays, score_min, recherche,
                                     sauf="source"),
                            moi.id),
            pays=_compter(session, Offer.pays,
                          _filtres(contrats, sources, pays, score_min, recherche, sauf="pays"),
                          moi.id),
        ),
    )


@router.get("/statistiques", response_model=Statistiques)
def statistiques(session: Session = Depends(get_session),
                 moi: Utilisateur = Depends(utilisateur_courant)) -> Statistiques:
    debut_journee = maintenant().replace(hour=0, minute=0, second=0, microsecond=0)

    def compter(*conditions):
        return session.exec(select(func.count()).select_from(Offer)
                            .join(ScoreOffre, _fil(moi.id)).where(*conditions)).one()

    scan = dernier_scan_abouti(session, moi.id)

    # « Nouvelles » = entrées dans le fil à la dernière recherche et pas encore
    # ouvertes. Compter toutes les offres jamais ouvertes donnerait un badge
    # bloqué à « 99+ » pendant des mois : le signal « il y a du neuf » s'y perdrait.
    nouvelles = compter(
        ScoreOffre.vue == False,  # noqa: E712 — SQLAlchemy exige ==
        ScoreOffre.ajoutee_le >= scan.started_at,
    ) if scan is not None else 0

    return Statistiques(
        total=compter(),
        expirees=compter(Offer.derniere_vue_le < _seuil_expiration()),
        aujourd_hui=compter(Offer.date_publication >= debut_journee),
        vie=compter(Offer.type_contrat == "V.I.E"),
        nouvelles=nouvelles,
        jamais_vues=compter(ScoreOffre.vue == False),  # noqa: E712
        non_scorees=compter(ScoreOffre.score.is_(None)),
        dernier_scan=scan.finished_at if scan else None,
    )


@router.post("/scorer", response_model=ResultatScoring)
def scorer(forcer: bool = False, session: Session = Depends(get_session),
           moi: Utilisateur = Depends(utilisateur_courant)) -> dict:
    """Recalcule les scores. Aucun appel LLM : c'est du code pur."""
    try:
        return scorer_toutes(session, moi.id, forcer=forcer)
    except ProfilVide as e:
        raise HTTPException(409, str(e)) from e


@router.get("/{offre_id}", response_model=OffreDetail)
def detail(offre_id: int, session: Session = Depends(get_session),
           moi: Utilisateur = Depends(utilisateur_courant)) -> OffreDetail:
    offre, suivi = suivi_de(session, offre_id, moi.id)
    if not suivi.vue:
        suivi.vue = True          # consulter une offre la retire du badge « nouvelles »
        session.add(suivi)
        session.commit()
        session.refresh(suivi)
        session.refresh(offre)
    candidature = session.exec(
        select(Application).where(Application.offer_id == offre_id,
                                  Application.utilisateur_id == moi.id)
    ).first()
    return OffreDetail(**fusion(offre, suivi), a_candidature=candidature is not None,
                       expiree=offre.derniere_vue_le < _seuil_expiration())


@router.get("/{offre_id}/correspondance")
def correspondance(offre_id: int, session: Session = Depends(get_session),
                   moi: Utilisateur = Depends(utilisateur_courant)) -> dict:
    """Ce que verra le recruteur dans son ATS — calculé sans aucun appel payant."""
    from ..documents.correspondance import correspondance_ats
    from ..services.scoring import profil_courant

    offre, _ = suivi_de(session, offre_id, moi.id)
    try:
        profil = profil_courant(session, moi.id)
    except ProfilVide as e:
        raise HTTPException(409, str(e)) from e
    return correspondance_ats(profil, offre)
