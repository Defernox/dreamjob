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
from ..models.base import maintenant

log = logging.getLogger("dreamjob.notification")

SERVEUR_NTFY = "https://ntfy.sh"
MAX_LIGNES = 5


def offres_a_signaler(session: Session, utilisateur_id: int, depuis: datetime,
                      seuil: float | None = None) -> list[tuple[Offer, ScoreOffre]]:
    """Entrées dans le fil du compte depuis `depuis`, notées au moins `seuil`
    (le vert par défaut), jamais ouvertes, jamais encore signalées."""
    if seuil is None:
        seuil = reglages().scoring.seuils.bon
    return list(session.exec(
        select(Offer, ScoreOffre)
        .join(ScoreOffre, ScoreOffre.offer_id == Offer.id)
        .where(ScoreOffre.utilisateur_id == utilisateur_id,
               ScoreOffre.ajoutee_le >= depuis, ScoreOffre.score >= seuil,
               ScoreOffre.vue == False,  # noqa: E712 — SQLAlchemy exige ==
               ScoreOffre.alertee_le.is_(None))
        .order_by(ScoreOffre.score.desc())
    ).all())


def _marquer(session: Session, offres: list[tuple[Offer, ScoreOffre]]) -> None:
    """Signalées : aucune alerte, ni aucun résumé, ne les reprendra."""
    instant = maintenant()
    for _, note in offres:
        note.alertee_le = instant
        session.add(note)
    session.commit()


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
            _marquer(session, offres)
            envoyees += 1
    return envoyees


# --- Les alertes de la veille ------------------------------------------------------------


def _depuis(date: datetime | None) -> str:
    """« publiée il y a 25 min » : c'est tout l'intérêt de l'alerte."""
    if date is None:
        return ""
    minutes = int((maintenant() - date).total_seconds() // 60)
    if minutes < 0:
        return ""
    if minutes < 60:
        return f"publiée il y a {max(minutes, 1)} min"
    if minutes < 24 * 60:
        return f"publiée il y a {minutes // 60} h"
    return f"publiée il y a {minutes // (24 * 60)} j"


def message_alerte(offre: Offer, note: ScoreOffre) -> tuple[str, str]:
    titre = f"{round(note.score)} · {offre.titre}"
    details = " · ".join(filter(None, [
        offre.entreprise, offre.lieu or offre.pays, offre.type_contrat,
        _depuis(offre.date_publication),
    ]))
    return titre, details or offre.titre


def alertes_du_jour(session: Session, utilisateur_id: int) -> int:
    debut = maintenant().replace(hour=0, minute=0, second=0, microsecond=0)
    return len(session.exec(select(ScoreOffre.offer_id).where(
        ScoreOffre.utilisateur_id == utilisateur_id,
        ScoreOffre.alertee_le >= debut)).all())


def alerter(session: Session, depuis: datetime) -> int:
    """Une notification par offre verte entrée dans le fil depuis `depuis` —
    une par offre, pour que chacune s'ouvre d'un geste — dans la limite de
    `veille.alertes_par_jour_max` par compte. Les suivantes restent pour le
    résumé du matin. Renvoie le nombre d'alertes parties. Ne lève jamais.
    """
    r = reglages()
    seuil = r.veille.seuil_alerte if r.veille.seuil_alerte is not None else r.scoring.seuils.bon
    envoyees = 0
    for utilisateur in session.exec(select(Utilisateur)).all():
        sujet = sujet_de(session, utilisateur)
        if not sujet:
            continue
        reste = r.veille.alertes_par_jour_max - alertes_du_jour(session, utilisateur.id)
        for offre, note in offres_a_signaler(session, utilisateur.id, depuis, seuil)[:max(0, reste)]:
            if _publier(sujet, *message_alerte(offre, note), offre_id=offre.id,
                        urgente=note.score >= URGENTE):
                _marquer(session, [(offre, note)])
                envoyees += 1
    return envoyees


# Au-dessus, l'alerte sonne même si le téléphone est réglé sur « discret ».
URGENTE = 90


def _publier(sujet: str, titre: str, corps: str, *, offre_id: int | None = None,
             urgente: bool = False) -> bool:
    entetes = {"Title": titre.encode("utf-8"), "Tags": "briefcase"}
    if urgente:
        entetes["Priority"] = "high"
    if adresse := reglages().adresse_publique:
        # Un clic ouvre la fiche de l'offre, pas la liste : c'est là qu'on
        # décide de postuler.
        chemin = f"/offres/{offre_id}" if offre_id else "/offres"
        entetes["Click"] = f"{adresse.rstrip('/')}{chemin}"
    try:
        httpx.post(f"{SERVEUR_NTFY}/{sujet}", content=corps.encode("utf-8"),
                   headers=entetes, timeout=15.0).raise_for_status()
    except httpx.HTTPError as e:
        log.warning("Notification non envoyée : %s", e)
        return False
    log.info("Notification envoyée : %s", titre)
    return True
