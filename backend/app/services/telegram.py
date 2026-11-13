"""Les appels à l'API du bot Telegram, en un seul endroit.

Trois gestes suffisent à tout ce que fait le bot : appeler une méthode, écrire
un message, déposer un fichier. Aucun ne lève — une panne de Telegram ne doit
arrêter ni la relève des réponses ni une candidature en cours — et aucun ne
journalise le texte d'une erreur `httpx` : il reprend l'adresse de la requête,
donc le jeton du bot.
"""

from __future__ import annotations

import html
import logging

import httpx

from .notification import SERVEUR_TELEGRAM

log = logging.getLogger("dreamjob.telegram")

# Limites de Telegram : au-delà, le message est refusé en entier.
TAILLE_MESSAGE = 4096
TAILLE_LEGENDE = 1024

SANS_CLAVIER = {"inline_keyboard": []}


def echapper(texte) -> str:
    """Pour un message en HTML : ce qui vient d'une annonce ou du profil ne doit
    pas être lu comme une balise."""
    return html.escape(str(texte or ""), quote=False)


def appeler(jeton: str, methode: str, charge: dict, delai: float = 15.0) -> dict | None:
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


def ecrire(jeton: str, conversation: str, texte: str, *, clavier: list[list[dict]] | None = None,
           en_html: bool = False) -> bool:
    """Un message dans la conversation. Trop long, il est coupé plutôt que refusé."""
    if len(texte) > TAILLE_MESSAGE:
        texte = texte[:TAILLE_MESSAGE - 1] + "…"
    charge: dict = {"chat_id": conversation, "text": texte, "disable_web_page_preview": True}
    if en_html:
        charge["parse_mode"] = "HTML"
    if clavier is not None:
        charge["reply_markup"] = {"inline_keyboard": clavier}
    return appeler(jeton, "sendMessage", charge) is not None


def deposer(jeton: str, conversation: str, nom: str, contenu: bytes, legende: str = "") -> bool:
    """Un fichier dans la conversation. Vrai s'il est parti."""
    donnees = {"chat_id": conversation}
    if legende:
        donnees["caption"] = legende[:TAILLE_LEGENDE]
    try:
        httpx.post(f"{SERVEUR_TELEGRAM}/bot{jeton}/sendDocument", data=donnees,
                   files={"document": (nom, contenu)}, timeout=60.0).raise_for_status()
    except httpx.HTTPStatusError as e:
        log.warning("Telegram sendDocument refusé (code %s).", e.response.status_code)
        return False
    except httpx.HTTPError as e:
        log.warning("Telegram sendDocument en échec (%s).", type(e).__name__)
        return False
    return True


def accuser(jeton: str, rappel: dict, texte: str = "") -> None:
    """L'accusé d'un appui sur un bouton : sans lui, le bouton tourne dans le vide."""
    charge: dict = {"callback_query_id": rappel.get("id")}
    if texte:
        charge["text"] = texte
    appeler(jeton, "answerCallbackQuery", charge)


def changer_clavier(jeton: str, conversation: str, message: dict, clavier: dict) -> None:
    """Remplace les boutons d'un message déjà envoyé (`SANS_CLAVIER` les retire)."""
    if message.get("message_id"):
        appeler(jeton, "editMessageReplyMarkup", {
            "chat_id": conversation, "message_id": message["message_id"], "reply_markup": clavier})
