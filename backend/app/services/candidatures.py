"""Le suivi des candidatures, hors de toute requête HTTP.

L'interface n'est plus seule à postuler : le bot Telegram enregistre une
candidature quand il vient de l'envoyer, et dépose le justificatif France
Travail sur demande (`/excel`). Ces deux gestes vivent ici pour que l'API et le
bot disent exactement la même chose.
"""

from __future__ import annotations

from sqlmodel import Session, desc, select

from ..models import Application, Offer, ScoreOffre
from ..models.base import maintenant
from ..models.enums import StatutCandidature


def de(session: Session, utilisateur_id: int, offre_id: int) -> Application | None:
    """La candidature du compte à cette offre, s'il a déjà postulé."""
    return session.exec(select(Application).where(
        Application.utilisateur_id == utilisateur_id, Application.offer_id == offre_id)).first()


def enregistrer(session: Session, utilisateur_id: int, offre_id: int, *, contact: str = "",
                notes: str = "", dossier: str = "") -> tuple[Application, bool]:
    """Note la candidature comme envoyée. Rend (candidature, créée) : une offre à
    laquelle le compte a déjà postulé garde sa ligne — une seconde validation ne
    crée pas de doublon et n'écrase ni sa date ni ses notes."""
    existante = de(session, utilisateur_id, offre_id)
    if existante is not None:
        return existante, False
    candidature = Application(utilisateur_id=utilisateur_id, offer_id=offre_id,
                              statut=StatutCandidature.ENVOYEE.value, contact=contact,
                              notes=notes, dossier_local=dossier)
    session.add(candidature)
    session.commit()
    session.refresh(candidature)
    return candidature, True


def lignes_export(session: Session, utilisateur_id: int) -> list[dict]:
    """Les candidatures du compte, de la plus récente à la plus ancienne, telles
    que `exports.excel.exporter` les attend."""
    candidatures = list(session.exec(
        select(Application).where(Application.utilisateur_id == utilisateur_id)
        .order_by(desc(Application.date_candidature))).all())
    if not candidatures:
        return []
    # Une seule requête pour toutes les offres, une pour toutes les notes : un
    # `session.get` par candidature ferait autant d'allers-retours que de lignes.
    identifiants = [c.offer_id for c in candidatures]
    offres = {o.id: o for o in session.exec(select(Offer).where(Offer.id.in_(identifiants))).all()}
    scores = {n.offer_id: n.score for n in session.exec(select(ScoreOffre).where(
        ScoreOffre.utilisateur_id == utilisateur_id, ScoreOffre.offer_id.in_(identifiants))).all()}
    lignes = []
    for candidature in candidatures:
        offre = offres.get(candidature.offer_id)
        lignes.append(candidature.model_dump() | {
            "titre": offre.titre if offre else "",
            "entreprise": offre.entreprise if offre else "",
            "pays": offre.pays if offre else "",
            "score": scores.get(candidature.offer_id),
            "url": offre.url if offre else "",
        })
    return lignes


def horodatage() -> str:
    """« 13/11/2026 » — pour une note lisible dans le justificatif."""
    return maintenant().strftime("%d/%m/%Y")
