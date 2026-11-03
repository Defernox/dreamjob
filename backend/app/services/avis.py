"""Les avis donnés d'un appui sous une alerte Telegram.

Chaque alerte porte deux boutons, « 👍 Intéressant » et « 👎 Pas pour moi »
(`notification.boutons_avis`). La réponse est rangée dans `ScoreOffre.avis` :
des étiquettes gratuites, posées en utilisant l'application, que
`outils/evaluer_score.py` relit pour mesurer le score. Elles ne le modifient
pas — un réglage se décide sur une mesure, pas d'un appui.

**Le serveur va chercher les réponses, Telegram ne vient pas les livrer.** Un
webhook demanderait une adresse publique ; le serveur n'en a pas et n'en aura
pas. Un fil interroge donc `getUpdates` en attente longue : Telegram garde la
requête ouverte jusqu'à vingt secondes et répond dès qu'un bouton est pressé —
l'accusé arrive aussitôt, sans rien ouvrir sur Internet.

**Seule la conversation du propriétaire est écoutée.** Le jeton du bot n'est pas
un secret absolu (il a transité par un navigateur) et le nom du bot se trouve :
un inconnu peut lui écrire et presser des boutons. Toute réponse qui ne vient
pas de `TELEGRAM_CHAT_ID` est ignorée, et une offre hors du fil du propriétaire
n'est jamais modifiée.

Les erreurs sont journalisées sans leur texte : celui d'`httpx` reprend
l'adresse de la requête, donc le jeton.
"""

from __future__ import annotations

import logging
import threading

import httpx
from sqlalchemy import update
from sqlmodel import Session, select

from ..models import ScoreOffre, Utilisateur
from ..models.base import maintenant
from .notification import AVIS, PREFIXE_AVIS, SERVEUR_TELEGRAM, _telegram, boutons_avis

log = logging.getLogger("dreamjob.avis")

ATTENTE_SECONDES = 20          # attente longue de getUpdates
PAUSE_APRES_ECHEC = 60         # une panne ne doit pas tourner en boucle serrée

_arret = threading.Event()
_fil: threading.Thread | None = None
_suivant: int | None = None    # premier update_id pas encore traité


def _appeler(jeton: str, methode: str, charge: dict, delai: float = 15.0) -> dict | None:
    """Un appel à l'API du bot. None si l'appel échoue, sans jamais lever."""
    try:
        reponse = httpx.post(f"{SERVEUR_TELEGRAM}/bot{jeton}/{methode}", json=charge, timeout=delai)
        reponse.raise_for_status()
        return reponse.json()
    except httpx.HTTPStatusError as e:
        log.warning("Telegram %s refusé (code %s).", methode, e.response.status_code)
    except (httpx.HTTPError, ValueError) as e:
        log.warning("Telegram %s en échec (%s).", methode, type(e).__name__)
    return None


def lire_avis(donnees: str) -> tuple[int, int] | None:
    """(offre, avis) depuis « avis:<offre>:<0|1> », sinon None."""
    morceaux = (donnees or "").split(":")
    if len(morceaux) != 3 or morceaux[0] != PREFIXE_AVIS:
        return None
    try:
        offre, valeur = int(morceaux[1]), int(morceaux[2])
    except ValueError:
        return None
    return (offre, valeur) if valeur in AVIS else None


def enregistrer(session: Session, offre_id: int, valeur: int) -> bool:
    """Range l'avis du propriétaire. Faux si l'offre n'est pas dans son fil."""
    proprietaire = session.exec(select(Utilisateur).where(Utilisateur.proprietaire == True)).first()  # noqa: E712
    if proprietaire is None:
        return False
    resultat = session.exec(update(ScoreOffre).where(
        ScoreOffre.utilisateur_id == proprietaire.id, ScoreOffre.offer_id == offre_id,
    ).values(avis=valeur, avis_le=maintenant()))
    session.commit()
    return resultat.rowcount == 1


def _clavier_coche(message: dict, offre_id: int, valeur: int) -> dict:
    """Le clavier de l'alerte, la ligne d'avis remplacée par sa version cochée ;
    le bouton « Ouvrir dans DreamJob » reste tel quel."""
    lignes = (message.get("reply_markup") or {}).get("inline_keyboard") or []
    gardees = [l for l in lignes
               if not any(str(b.get("callback_data", "")).startswith(f"{PREFIXE_AVIS}:") for b in l)]
    return {"inline_keyboard": gardees + [boutons_avis(offre_id, valeur)]}


def traiter(session: Session, mise_a_jour: dict, jeton: str, conversation: str) -> bool:
    """Une réponse de Telegram. Vrai si un avis a été enregistré."""
    rappel = mise_a_jour.get("callback_query")
    if not rappel:
        return False
    message = rappel.get("message") or {}
    if str((message.get("chat") or {}).get("id")) != str(conversation):
        log.warning("Avis venu d'une autre conversation que celle du propriétaire : ignoré.")
        return False
    lu = lire_avis(rappel.get("data", ""))
    if lu is None:
        _appeler(jeton, "answerCallbackQuery", {"callback_query_id": rappel.get("id")})
        return False
    offre_id, valeur = lu
    if not enregistrer(session, offre_id, valeur):
        _appeler(jeton, "answerCallbackQuery", {"callback_query_id": rappel.get("id"),
                                                "text": "Offre introuvable."})
        return False
    _appeler(jeton, "answerCallbackQuery", {"callback_query_id": rappel.get("id"),
                                            "text": f"Noté : {AVIS[valeur]}"})
    if message.get("message_id"):
        _appeler(jeton, "editMessageReplyMarkup", {
            "chat_id": conversation, "message_id": message["message_id"],
            "reply_markup": _clavier_coche(message, offre_id, valeur)})
    log.info("Avis %s sur l'offre %s.", valeur, offre_id)
    return True


def relever(moteur, attente: int = ATTENTE_SECONDES) -> int | None:
    """Une relève : attend au plus `attente` secondes, traite ce qui arrive.
    Rend le nombre d'avis enregistrés, ou None si Telegram n'a pas répondu."""
    global _suivant
    identifiants = _telegram()
    if identifiants is None:
        return 0
    jeton, conversation = identifiants
    charge: dict = {"timeout": attente, "allowed_updates": ["callback_query"]}
    if _suivant is not None:
        charge["offset"] = _suivant
    reponse = _appeler(jeton, "getUpdates", charge, delai=attente + 10)
    if reponse is None or not reponse.get("ok"):
        return None
    enregistres = 0
    with Session(moteur) as session:
        for mise_a_jour in reponse.get("result", []):
            # Avancer d'abord : une réponse qui fait échouer le traitement ne
            # doit pas revenir en boucle à chaque relève.
            _suivant = mise_a_jour["update_id"] + 1
            try:
                enregistres += traiter(session, mise_a_jour, jeton, conversation)
            except Exception:  # noqa: BLE001 — un avis raté ne doit pas arrêter le fil
                log.exception("Avis Telegram non traité")
    return enregistres


def _boucle(moteur) -> None:
    while not _arret.is_set():
        if relever(moteur) is None:
            _arret.wait(PAUSE_APRES_ECHEC)


def demarrer(moteur) -> bool:
    """Lance le fil de relève, si Telegram est réglé. Vrai s'il tourne."""
    global _fil
    if _telegram() is None:
        return False
    _arret.clear()
    if _fil is not None and _fil.is_alive():
        # Un redémarrage du planificateur (arrêter puis démarrer) : le fil, encore
        # dans son attente, repart pour un tour au lieu de s'éteindre.
        return True
    # Démon : il ne retient jamais l'arrêt de l'application, même au milieu
    # d'une attente longue.
    _fil = threading.Thread(target=_boucle, args=(moteur,), name="avis-telegram", daemon=True)
    _fil.start()
    log.info("Avis Telegram : relève des réponses lancée.")
    return True


def arreter() -> None:
    _arret.set()


def _reinitialiser() -> None:
    """Pour les tests : oublie la position de lecture."""
    global _suivant
    _suivant = None


