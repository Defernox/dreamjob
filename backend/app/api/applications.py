"""Les candidatures : création depuis une offre, consultation, mise à jour.

Le tableau de suivi et l'export Excel arrivent à l'étape 7 ; ce qui est ici
suffit au bouton « Postuler » de l'écran Détail.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlmodel import Session, desc, select

from ..db import get_session
from ..exports.excel import exporter, lire
from ..models import Application, Offer
from ..models.base import maintenant
from ..models.enums import StatutCandidature
from ..schemas.candidature import CandidatureCreation, CandidatureLecture, CandidatureMaj
from ..scoring.texte import normaliser

router = APIRouter(prefix="/api/candidatures", tags=["candidatures"])


def _en_lecture(candidature: Application, offre: Offer | None) -> CandidatureLecture:
    return CandidatureLecture(
        **candidature.model_dump(),
        titre=offre.titre if offre else "",
        entreprise=offre.entreprise if offre else "",
        pays=offre.pays if offre else "",
        score=offre.score if offre else None,
        url=offre.url if offre else "",
    )


@router.get("", response_model=list[CandidatureLecture])
def lister(session: Session = Depends(get_session)) -> list[CandidatureLecture]:
    candidatures = session.exec(
        select(Application).order_by(desc(Application.date_candidature))
    ).all()
    return [_en_lecture(c, session.get(Offer, c.offer_id)) for c in candidatures]


@router.get("/export.xlsx")
def exporter_xlsx(session: Session = Depends(get_session)) -> Response:
    """Le justificatif de recherche d'emploi, prêt à envoyer à France Travail."""
    candidatures = list(session.exec(
        select(Application).order_by(desc(Application.date_candidature))
    ).all())
    # Une seule requête pour toutes les offres : un `session.get` par
    # candidature ferait autant d'allers-retours que de lignes exportées.
    offres = {
        o.id: o for o in session.exec(
            select(Offer).where(Offer.id.in_([c.offer_id for c in candidatures]))
        ).all()
    } if candidatures else {}

    lignes = []
    for candidature in candidatures:
        offre = offres.get(candidature.offer_id)
        lignes.append(candidature.model_dump() | {
            "titre": offre.titre if offre else "",
            "entreprise": offre.entreprise if offre else "",
            "pays": offre.pays if offre else "",
            "score": offre.score if offre else None,
            "url": offre.url if offre else "",
        })

    jour = date.today().isoformat()
    return Response(
        content=exporter(lignes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="candidatures-{jour}.xlsx"'},
    )


@router.post("/importer")
async def importer_xlsx(
    fichier: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    """Reprend le suivi depuis un export existant.

    Ne crée jamais de candidature : une candidature sans offre en base serait un
    fantôme. On met à jour ce qui correspond, on signale le reste.
    """
    if not (fichier.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Format attendu : .xlsx")

    try:
        reprise = lire(await fichier.read())
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

    # Index des candidatures existantes, par URL puis par entreprise + poste.
    par_url: dict[str, Application] = {}
    par_libelle: dict[tuple[str, str], Application] = {}
    for candidature in session.exec(select(Application)).all():
        offre = session.get(Offer, candidature.offer_id)
        if offre is None:
            continue
        if offre.url:
            par_url[offre.url] = candidature
        par_libelle[(normaliser(offre.entreprise), normaliser(offre.titre))] = candidature

    for ligne in reprise.lignes:
        cible = par_url.get(ligne["url"]) or par_libelle.get(
            (normaliser(ligne["entreprise"]), normaliser(ligne["titre"]))
        )
        if cible is None:
            reprise.ignorees += 1
            reprise.problemes.append(
                f"Ligne {ligne['ligne']} : « {ligne['titre']} » chez "
                f"« {ligne['entreprise']} » ne correspond à aucune offre en base."
            )
            continue

        for champ in ("statut", "notes", "contact", "deadline"):
            if ligne[champ]:
                setattr(cible, champ, ligne[champ])
        cible.updated_at = maintenant()
        session.add(cible)
        reprise.mises_a_jour += 1

    session.commit()
    return {
        "mises_a_jour": reprise.mises_a_jour,
        "ignorees": reprise.ignorees,
        "problemes": reprise.problemes[:20],
    }


@router.post("", response_model=CandidatureLecture, status_code=201)
def creer(
    creation: CandidatureCreation,
    session: Session = Depends(get_session),
) -> CandidatureLecture:
    offre = session.get(Offer, creation.offer_id)
    if offre is None:
        raise HTTPException(404, "Offre introuvable.")

    # Cliquer deux fois sur « Postuler » ne doit pas créer de doublon : on
    # renvoie la candidature existante plutôt qu'une erreur.
    existante = session.exec(
        select(Application).where(Application.offer_id == creation.offer_id)
    ).first()
    if existante is not None:
        return _en_lecture(existante, offre)

    candidature = Application(
        offer_id=creation.offer_id,
        statut=creation.statut or StatutCandidature.ENVOYEE.value,
        notes=creation.notes,
        contact=creation.contact,
        deadline=creation.deadline,
    )
    session.add(candidature)
    session.commit()
    session.refresh(candidature)
    return _en_lecture(candidature, offre)


@router.patch("/{candidature_id}", response_model=CandidatureLecture)
def modifier(
    candidature_id: int,
    maj: CandidatureMaj,
    session: Session = Depends(get_session),
) -> CandidatureLecture:
    candidature = session.get(Application, candidature_id)
    if candidature is None:
        raise HTTPException(404, "Candidature introuvable.")

    for champ, valeur in maj.model_dump(exclude_unset=True).items():
        if valeur is not None:
            setattr(candidature, champ, valeur)
    candidature.updated_at = maintenant()
    session.add(candidature)
    session.commit()
    session.refresh(candidature)
    return _en_lecture(candidature, session.get(Offer, candidature.offer_id))


@router.delete("/{candidature_id}", status_code=204)
def supprimer(candidature_id: int, session: Session = Depends(get_session)) -> None:
    candidature = session.get(Application, candidature_id)
    if candidature is None:
        raise HTTPException(404, "Candidature introuvable.")
    session.delete(candidature)
    session.commit()
