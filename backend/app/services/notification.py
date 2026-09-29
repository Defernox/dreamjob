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
from datetime import datetime, timedelta

import httpx
from sqlalchemy import update
from sqlmodel import Session, select

from ..config import reglages
from ..models import Offer, Profile, ScoreOffre, Utilisateur
from ..models.base import maintenant
from .doublons import meme_poste

log = logging.getLogger("dreamjob.notification")

SERVEUR_NTFY = "https://ntfy.sh"
MAX_LIGNES = 5

Paire = tuple[Offer, ScoreOffre]


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


# --- Le contrôle des doublons -----------------------------------------------------------
#
# Trois façons de sonner deux fois pour un même poste, trois parades :
#
# 1. **Le même poste d'une source à l'autre**, ou dans dix agences : les offres
#    sont regroupées (`doublons.meme_poste`) ; seule la mieux notée part, les
#    autres sont marquées « signalées » avec `doublon_de`. Contre ce qui a déjà
#    sonné, la comparaison remonte sur `veille.doublons_jours`.
# 2. **Deux passes concurrentes** (une seconde instance, un redémarrage au mauvais
#    moment) : l'offre est RÉSERVÉE avant l'envoi, par une écriture atomique qui
#    ne réussit que si personne ne l'a signalée entre-temps. Qui n'obtient pas
#    la réservation n'envoie rien.
# 3. **Un envoi dont on ignore l'issue** (délai dépassé après l'envoi) : il est
#    tenu pour parti. Seul un échec certain — connexion refusée, réponse
#    d'erreur de ntfy — libère la réservation pour la passe suivante. Mieux vaut
#    une alerte perdue, rattrapée par l'écran, qu'une alerte en double.


def deja_signalees(session: Session, utilisateur_id: int, depuis: datetime) -> list[Offer]:
    """Les offres déjà signalées à ce compte depuis `depuis` — alertes, résumés
    et doublons compris : un poste qu'on a déjà vu passer ne sonne plus."""
    return list(session.exec(
        select(Offer).join(ScoreOffre, ScoreOffre.offer_id == Offer.id)
        .where(ScoreOffre.utilisateur_id == utilisateur_id, ScoreOffre.alertee_le >= depuis)
    ).all())


def regrouper(offres: list[Paire], deja: list[Offer]) -> tuple[list[list[Paire]], list[tuple[Offer, ScoreOffre, int]]]:
    """(groupes à signaler, doublons de ce qui l'a déjà été).

    Chaque groupe est un même poste ; son premier élément, le mieux noté (les
    offres arrivent triées par note), est celui qui part. Un doublon porte
    l'identifiant de l'offre déjà signalée qu'il répète."""
    groupes: list[list[Paire]] = []
    doublons: list[tuple[Offer, ScoreOffre, int]] = []
    for offre, note in offres:
        ancienne = next((d for d in deja if meme_poste(offre, d)), None)
        if ancienne is not None:
            doublons.append((offre, note, ancienne.id))
            continue
        groupe = next((g for g in groupes if meme_poste(offre, g[0][0])), None)
        if groupe is not None:
            groupe.append((offre, note))
        else:
            groupes.append([(offre, note)])
    return groupes, doublons


def _marquer_doublons(session: Session, doublons: list[tuple[Offer, ScoreOffre, int]]) -> None:
    """Un doublon est « signalé » par son jumeau : aucun résumé ne le reprendra.
    Il ne compte pas dans le plafond du jour — rien n'a sonné."""
    instant = maintenant()
    for _, note, reference in doublons:
        session.exec(update(ScoreOffre).where(
            ScoreOffre.utilisateur_id == note.utilisateur_id, ScoreOffre.offer_id == note.offer_id,
            ScoreOffre.alertee_le.is_(None)).values(alertee_le=instant, doublon_de=reference))
    session.commit()


def _reserver(session: Session, groupe: list[Paire]) -> datetime | None:
    """Réserve un groupe avant de l'envoyer. L'écriture ne réussit que si l'offre
    principale n'a été signalée par personne entre-temps : deux passes
    concurrentes ne peuvent pas envoyer la même. Rend l'instant de la
    réservation, ou None si une autre passe l'a déjà prise."""
    instant = maintenant()
    (principale, note), jumeaux = groupe[0], groupe[1:]
    prise = session.exec(update(ScoreOffre).where(
        ScoreOffre.utilisateur_id == note.utilisateur_id, ScoreOffre.offer_id == note.offer_id,
        ScoreOffre.alertee_le.is_(None)).values(alertee_le=instant, doublon_de=None))
    if prise.rowcount != 1:
        session.rollback()
        return None
    for _, jumeau in jumeaux:
        session.exec(update(ScoreOffre).where(
            ScoreOffre.utilisateur_id == jumeau.utilisateur_id, ScoreOffre.offer_id == jumeau.offer_id,
            ScoreOffre.alertee_le.is_(None)).values(alertee_le=instant, doublon_de=principale.id))
    session.commit()
    return instant


def _liberer(session: Session, groupe: list[Paire], instant: datetime) -> None:
    """L'envoi a échoué pour de bon : la passe suivante réessaiera."""
    for _, note in groupe:
        session.exec(update(ScoreOffre).where(
            ScoreOffre.utilisateur_id == note.utilisateur_id, ScoreOffre.offer_id == note.offer_id,
            ScoreOffre.alertee_le == instant).values(alertee_le=None, doublon_de=None))
    session.commit()


def _autres_lieux(groupe: list[Paire]) -> int:
    principal = groupe[0][0]
    return len({o.lieu or o.pays for o, _ in groupe[1:]} - {principal.lieu or principal.pays})


def message(groupes: list[list[Paire]]) -> tuple[str, str]:
    """Le résumé : un poste par ligne, quel que soit le nombre de sources ou
    d'agences qui le publient."""
    titre = (f"{len(groupes)} nouvelle offre verte" if len(groupes) == 1
             else f"{len(groupes)} nouvelles offres vertes")
    lignes = []
    for groupe in groupes[:MAX_LIGNES]:
        o, s = groupe[0]
        autres = _autres_lieux(groupe)
        lignes.append(f"{round(s.score)} — {o.titre}" + (f" · {o.entreprise}" if o.entreprise else "")
                      + (f" (+{autres} lieu{'x' if autres > 1 else ''})" if autres else ""))
    if len(groupes) > MAX_LIGNES:
        lignes.append(f"… et {len(groupes) - MAX_LIGNES} autres")
    return titre, "\n".join(lignes)


def sujet_de(session: Session, utilisateur: Utilisateur) -> str | None:
    """Le sujet ntfy d'un compte : celui de son profil, sinon — pour le seul
    propriétaire — celui de `.env`. Un ami ne reçoit jamais les notifications
    d'un autre."""
    profil = session.exec(select(Profile).where(Profile.utilisateur_id == utilisateur.id)).first()
    if profil is not None and profil.ntfy_sujet.strip():
        return profil.ntfy_sujet.strip()
    return reglages().secret("NTFY_SUJET") if utilisateur.proprietaire else None


class _Deja:
    """Ce qui est déjà parti vers chaque sujet pendant cette passe : deux comptes
    réglés sur le même téléphone ne le font pas sonner deux fois."""

    def __init__(self) -> None:
        self.par_sujet: dict[str, list[Offer]] = {}

    def pour(self, sujet: str) -> list[Offer]:
        return self.par_sujet.setdefault(sujet, [])


def _a_envoyer(session: Session, utilisateur_id: int, offres: list[Paire], sujet: str,
               passe: _Deja) -> list[list[Paire]]:
    """Les groupes qui restent à envoyer, une fois écartés — et marqués — les
    doublons de ce qui a déjà sonné, pour ce compte ou sur ce sujet."""
    fenetre = maintenant() - timedelta(days=reglages().veille.doublons_jours)
    groupes, doublons = regrouper(offres, deja_signalees(session, utilisateur_id, fenetre)
                                  + passe.pour(sujet))
    _marquer_doublons(session, doublons)
    return groupes


def notifier(session: Session, depuis: datetime) -> int:
    """Publie le résumé de chaque compte. Renvoie le nombre de notifications parties.

    Ne lève jamais : une notification manquée ne doit pas faire échouer un
    scan qui, lui, a réussi.
    """
    envoyees = 0
    passe = _Deja()
    for utilisateur in session.exec(select(Utilisateur)).all():
        sujet = sujet_de(session, utilisateur)
        if not sujet:
            continue
        groupes = _a_envoyer(session, utilisateur.id, offres_a_signaler(session, utilisateur.id, depuis),
                             sujet, passe)
        reserves = [(g, instant) for g in groupes if (instant := _reserver(session, g)) is not None]
        if not reserves:
            continue
        if _publier(sujet, *message([g for g, _ in reserves])):
            passe.pour(sujet).extend(o for g, _ in reserves for o, _ in g)
            envoyees += 1
        else:
            for groupe, instant in reserves:
                _liberer(session, groupe, instant)
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


def message_alerte(offre: Offer, note: ScoreOffre, autres_lieux: int = 0) -> tuple[str, str]:
    titre = f"{round(note.score)} · {offre.titre}"
    lieu = offre.lieu or offre.pays
    if autres_lieux:
        lieu = f"{lieu} et {autres_lieux} autre{'s' if autres_lieux > 1 else ''} lieu{'x' if autres_lieux > 1 else ''}"
    details = " · ".join(filter(None, [
        offre.entreprise, lieu, offre.type_contrat, _depuis(offre.date_publication),
    ]))
    return titre, details or offre.titre


def alertes_du_jour(session: Session, utilisateur_id: int) -> int:
    """Ce qui a sonné aujourd'hui. Un doublon, signalé par son jumeau, n'a pas
    sonné : il ne consomme pas le plafond."""
    debut = maintenant().replace(hour=0, minute=0, second=0, microsecond=0)
    return len(session.exec(select(ScoreOffre.offer_id).where(
        ScoreOffre.utilisateur_id == utilisateur_id,
        ScoreOffre.alertee_le >= debut, ScoreOffre.doublon_de.is_(None))).all())


def alerter(session: Session, depuis: datetime) -> int:
    """Une notification par offre verte entrée dans le fil depuis `depuis` —
    une par offre, pour que chacune s'ouvre d'un geste — dans la limite de
    `veille.alertes_par_jour_max` par compte. Les suivantes restent pour le
    résumé du matin. Renvoie le nombre d'alertes parties. Ne lève jamais.
    """
    r = reglages()
    seuil = r.veille.seuil_alerte if r.veille.seuil_alerte is not None else r.scoring.seuils.bon
    fraiche = maintenant() - timedelta(days=r.veille.fraicheur_alerte_jours)
    envoyees = 0
    passe = _Deja()
    for utilisateur in session.exec(select(Utilisateur)).all():
        sujet = sujet_de(session, utilisateur)
        if not sujet:
            continue
        reste = r.veille.alertes_par_jour_max - alertes_du_jour(session, utilisateur.id)
        fraiches = [(o, n) for o, n in offres_a_signaler(session, utilisateur.id, depuis, seuil)
                    if o.date_publication is None or o.date_publication >= fraiche]
        # Les doublons d'abord, et tous : même au-delà du plafond, un poste déjà
        # signalé ne doit pas revenir dans le résumé du matin.
        for groupe in _a_envoyer(session, utilisateur.id, fraiches, sujet, passe)[:max(0, reste)]:
            instant = _reserver(session, groupe)
            if instant is None:
                continue                        # une autre passe l'a déjà pris
            offre, note = groupe[0]
            if _publier(sujet, *message_alerte(offre, note, _autres_lieux(groupe)), offre_id=offre.id,
                        urgente=note.score >= URGENTE):
                passe.pour(sujet).extend(o for o, _ in groupe)
                envoyees += 1
            else:
                _liberer(session, groupe, instant)
    return envoyees


# Au-dessus, l'alerte sonne même si le téléphone est réglé sur « discret ».
URGENTE = 90


def _publier(sujet: str, titre: str, corps: str, *, offre_id: int | None = None,
             urgente: bool = False) -> bool:
    """Vrai si la notification est partie — ou si l'on ne peut pas savoir.

    Un délai dépassé APRÈS l'envoi (lecture de la réponse) laisse l'issue
    inconnue : ntfy a pu la recevoir. La tenir pour échouée ferait réessayer, et
    sonner deux fois. Seuls une connexion impossible ou un refus de ntfy sont
    des échecs certains."""
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
    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError, httpx.ReadError) as e:
        log.warning("Notification peut-être envoyée (%s) : tenue pour partie, sans nouvel essai.", e)
        return True
    except httpx.HTTPError as e:
        log.warning("Notification non envoyée : %s", e)
        return False
    log.info("Notification envoyée : %s", titre)
    return True
