"""Le résumé du matin : les nouvelles offres vertes, sur le téléphone.

C'est ce qu'un serveur apporte vraiment : le scan tourne chaque jour, et
l'utilisateur n'a plus besoin d'ouvrir l'application pour savoir s'il y a du
neuf. Sans offre verte, aucune notification — une alerte quotidienne « rien de
nouveau » apprend vite à ignorer les autres.

Le canal est **ntfy** : une application gratuite (Android, iOS), sans compte,
qui reçoit ce qu'on publie sur un « sujet ». Le nom du sujet tient lieu de mot
de passe — il se choisit long et imprévisible. Chaque compte saisit le sien
dans son profil ; le propriétaire peut aussi le fixer dans `.env`
(`NTFY_SUJET`). Ce qui transite : intitulés, employeurs et scores, jamais le
profil ni les documents.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx
from sqlmodel import Session, select

from ..config import reglages
from ..models import Offer, Profile, ScoreOffre, Utilisateur

log = logging.getLogger("dreamjob.notification")

SERVEUR_NTFY = "https://ntfy.sh"
MAX_LIGNES = 5


def offres_a_signaler(session: Session, utilisateur_id: int,
                      depuis: datetime) -> list[tuple[Offer, ScoreOffre]]:
    """Entrées dans le fil du compte depuis `depuis`, notées au moins « bon »,
    jamais ouvertes."""
    seuil = reglages().scoring.seuils.bon
    return list(session.exec(
        select(Offer, ScoreOffre)
        .join(ScoreOffre, ScoreOffre.offer_id == Offer.id)
        .where(ScoreOffre.utilisateur_id == utilisateur_id,
               ScoreOffre.ajoutee_le >= depuis, ScoreOffre.score >= seuil,
               ScoreOffre.vue == False)  # noqa: E712 — SQLAlchemy exige ==
        .order_by(ScoreOffre.score.desc())
    ).all())


def message(offres: list[tuple[Offer, ScoreOffre]]) -> tuple[str, str]:
    titre = (f"{len(offres)} nouvelle offre verte" if len(offres) == 1
             else f"{len(offres)} nouvelles offres vertes")
    lignes = [f"{round(s.score)} — {o.titre}" + (f" · {o.entreprise}" if o.entreprise else "")
              for o, s in offres[:MAX_LIGNES]]
    if len(offres) > MAX_LIGNES:
        lignes.append(f"… et {len(offres) - MAX_LIGNES} autres")
    return titre, "\n".join(lignes)


def sujet_de(session: Session, utilisateur: Utilisateur) -> str | None:
    """Le sujet ntfy d'un compte : celui de son profil, sinon — pour le seul
    propriétaire — celui de `.env`. Un ami ne reçoit jamais les notifications
    d'un autre."""
    profil = session.exec(select(Profile).where(Profile.utilisateur_id == utilisateur.id)).first()
    if profil is not None and profil.ntfy_sujet.strip():
        return profil.ntfy_sujet.strip()
    return reglages().secret("NTFY_SUJET") if utilisateur.proprietaire else None


def notifier(session: Session, depuis: datetime) -> int:
    """Publie le résumé de chaque compte. Renvoie le nombre de notifications parties.

    Ne lève jamais : une notification manquée ne doit pas faire échouer un
    scan qui, lui, a réussi.
    """
    envoyees = 0
    for utilisateur in session.exec(select(Utilisateur)).all():
        sujet = sujet_de(session, utilisateur)
        if not sujet:
            continue
        offres = offres_a_signaler(session, utilisateur.id, depuis)
        if offres and _publier(sujet, *message(offres)):
            envoyees += 1
    return envoyees


def _publier(sujet: str, titre: str, corps: str) -> bool:
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
