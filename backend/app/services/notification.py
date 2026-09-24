"""Le résumé du matin : les nouvelles offres vertes, sur le téléphone.

C'est ce qu'un serveur apporte vraiment : le scan tourne chaque jour, et
l'utilisateur n'a plus besoin d'ouvrir l'application pour savoir s'il y a du
neuf. Sans offre verte, aucune notification — une alerte quotidienne « rien de
nouveau » apprend vite à ignorer les autres.

Le canal est **ntfy** : une application gratuite (Android, iOS), sans compte,
qui reçoit ce qu'on publie sur un « sujet ». Le nom du sujet tient lieu de mot
de passe — il se choisit long et imprévisible, et vit dans `.env`
(`NTFY_SUJET`). Ce qui transite : intitulés, employeurs et scores, jamais le
profil ni les documents.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx
from sqlmodel import Session, select

from ..config import reglages
from ..models import Offer

log = logging.getLogger("dreamjob.notification")

SERVEUR_NTFY = "https://ntfy.sh"
MAX_LIGNES = 5


def offres_a_signaler(session: Session, depuis: datetime) -> list[Offer]:
    """Arrivées depuis `depuis`, notées au moins « bon », jamais ouvertes."""
    seuil = reglages().scoring.seuils.bon
    return list(session.exec(
        select(Offer)
        .where(Offer.date_recuperation >= depuis, Offer.score >= seuil,
               Offer.vue == False)  # noqa: E712 — SQLAlchemy exige ==
        .order_by(Offer.score.desc())
    ).all())


def message(offres: list[Offer]) -> tuple[str, str]:
    titre = (f"{len(offres)} nouvelle offre verte" if len(offres) == 1
             else f"{len(offres)} nouvelles offres vertes")
    lignes = [f"{round(o.score)} — {o.titre}" + (f" · {o.entreprise}" if o.entreprise else "")
              for o in offres[:MAX_LIGNES]]
    if len(offres) > MAX_LIGNES:
        lignes.append(f"… et {len(offres) - MAX_LIGNES} autres")
    return titre, "\n".join(lignes)


def notifier(session: Session, depuis: datetime) -> bool:
    """Publie le résumé. Vrai si une notification est partie.

    Ne lève jamais : une notification manquée ne doit pas faire échouer un
    scan qui, lui, a réussi.
    """
    sujet = reglages().secret("NTFY_SUJET")
    if not sujet:
        return False
    offres = offres_a_signaler(session, depuis)
    if not offres:
        return False
    titre, corps = message(offres)
    entetes = {"Title": titre.encode("utf-8"), "Tags": "briefcase"}
    if adresse := reglages().adresse_publique:
        entetes["Click"] = f"{adresse.rstrip('/')}/offres"
    try:
        httpx.post(f"{SERVEUR_NTFY}/{sujet}", content=corps.encode("utf-8"),
                   headers=entetes, timeout=15.0).raise_for_status()
    except httpx.HTTPError as e:
        log.warning("Notification non envoyée : %s", e)
        return False
    log.info("Notification envoyée : %s", titre)
    return True
