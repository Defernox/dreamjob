"""Mots de passe, sessions, et le verrou devant l'API.

**Aucune dépendance ajoutée.** `hashlib.scrypt` est dans la bibliothèque
standard et résiste au calcul massif — c'est ce qu'on lui demande. Le mot de
passe n'est jamais stocké, jamais journalisé, jamais renvoyé.

**On stocke l'empreinte du jeton de session, pas le jeton.** Le navigateur
garde le jeton dans un cookie `HttpOnly` que le JavaScript de la page ne peut
pas lire ; la base n'en garde que le SHA-256. Une copie de la base — une
sauvegarde égarée — ne permet donc pas d'ouvrir une session.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
import time
from collections import deque
from datetime import timedelta

from sqlmodel import Session, select

from ..models import EMAIL_LOCAL, SessionUtilisateur, Utilisateur
from ..models.base import maintenant

log = logging.getLogger("dreamjob.acces")

COOKIE = "dreamjob_session"
DUREE_SESSION = timedelta(days=30)
LONGUEUR_MIN = 12

# scrypt : ~16 Mo de mémoire et quelques dizaines de millisecondes par essai.
# Négligeable pour une connexion, dissuasif pour qui teste des millions de
# mots de passe sur une base volée.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1

# Au-delà de ESSAIS_MAX échecs en FENETRE secondes depuis une même adresse, la
# connexion est refusée sans même vérifier le mot de passe.
ESSAIS_MAX = 10
FENETRE = 15 * 60


class MotDePasseTropCourt(ValueError):
    pass


# ----------------------------------------------------------- mots de passe


def hacher(mot_de_passe: str) -> str:
    if len(mot_de_passe) < LONGUEUR_MIN:
        raise MotDePasseTropCourt(
            f"Le mot de passe doit faire au moins {LONGUEUR_MIN} caractères.")
    sel = secrets.token_bytes(16)
    empreinte = hashlib.scrypt(mot_de_passe.encode("utf-8"), salt=sel,
                               n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${sel.hex()}${empreinte.hex()}"


def verifier(mot_de_passe: str, stocke: str) -> bool:
    try:
        algo, n, r, p, sel, attendu = stocke.split("$")
        if algo != "scrypt":
            return False
        calcule = hashlib.scrypt(mot_de_passe.encode("utf-8"), salt=bytes.fromhex(sel),
                                 n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    # Comparaison à temps constant : la durée ne révèle pas combien d'octets
    # concordent.
    return hmac.compare_digest(calcule.hex(), attendu)


# -------------------------------------------------------------- sessions


def _empreinte(jeton: str) -> str:
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


def ouvrir_session(session: Session, utilisateur: Utilisateur) -> str:
    """Renvoie le jeton à poser dans le cookie — la seule fois où il existe en clair."""
    jeton = secrets.token_urlsafe(32)
    session.add(SessionUtilisateur(empreinte=_empreinte(jeton), utilisateur_id=utilisateur.id,
                                   expire_le=maintenant() + DUREE_SESSION))
    utilisateur.derniere_connexion = maintenant()
    session.add(utilisateur)
    session.commit()
    return jeton


def utilisateur_de(session: Session, jeton: str | None) -> Utilisateur | None:
    if not jeton:
        return None
    ouverte = session.get(SessionUtilisateur, _empreinte(jeton))
    if ouverte is None:
        return None
    if ouverte.expire_le < maintenant():
        session.delete(ouverte)
        session.commit()
        return None
    return session.get(Utilisateur, ouverte.utilisateur_id)


def fermer_session(session: Session, jeton: str | None) -> None:
    if not jeton:
        return
    ouverte = session.get(SessionUtilisateur, _empreinte(jeton))
    if ouverte is not None:
        session.delete(ouverte)
        session.commit()


def authentifier(session: Session, email: str, mot_de_passe: str) -> Utilisateur | None:
    utilisateur = session.exec(
        select(Utilisateur).where(Utilisateur.email == email.strip().lower())).first()
    if utilisateur is None:
        # Même coût qu'une vraie vérification : la durée de réponse ne dit pas
        # si l'adresse existe.
        verifier(mot_de_passe, _EMPREINTE_LEURRE)
        return None
    return utilisateur if verifier(mot_de_passe, utilisateur.mot_de_passe) else None


def creer_utilisateur(session: Session, email: str, mot_de_passe: str) -> Utilisateur:
    """Crée un compte — ou reprend le compte local, s'il n'a jamais été réclamé.

    Le premier compte créé sur une base devient le propriétaire, et hérite des
    données d'une installation locale (profil, candidatures, recherches). Les
    suivants partent d'un profil vide, avec le budget mensuel par défaut.
    """
    from ..config import reglages

    empreinte = hacher(mot_de_passe)
    email = email.strip().lower()
    local = session.exec(select(Utilisateur).where(Utilisateur.email == EMAIL_LOCAL)).first()
    if local is not None:
        local.email, local.mot_de_passe = email, empreinte
        utilisateur = local
    elif session.exec(select(Utilisateur)).first() is None:
        utilisateur = Utilisateur(email=email, mot_de_passe=empreinte, proprietaire=True)
    else:
        utilisateur = Utilisateur(email=email, mot_de_passe=empreinte,
                                  budget_mensuel_usd=reglages().comptes.budget_mensuel_usd)
    session.add(utilisateur)
    session.commit()
    session.refresh(utilisateur)
    return utilisateur


def proprietaire(session: Session) -> Utilisateur:
    """Le compte propriétaire, créé d'office s'il n'existe pas encore.

    C'est l'utilisateur servi en local, où personne ne se connecte : une
    installation qui n'a jamais eu de compte continue de fonctionner comme
    avant, ses données rattachées à ce compte-là.
    """
    trouve = session.exec(
        select(Utilisateur).order_by(Utilisateur.proprietaire.desc(), Utilisateur.id)).first()
    if trouve is not None:
        if not trouve.proprietaire:
            # Une base où des comptes existaient avant la notion de
            # propriétaire : le plus ancien l'est.
            trouve.proprietaire = True
            session.add(trouve)
            session.commit()
        return trouve
    local = Utilisateur(email=EMAIL_LOCAL, mot_de_passe="", proprietaire=True)
    session.add(local)
    session.commit()
    session.refresh(local)
    return local


_EMPREINTE_LEURRE = hacher(secrets.token_urlsafe(16))


# ------------------------------------------------------- essais répétés


class Limiteur:
    """Compte les échecs de connexion par adresse, sur une fenêtre glissante.

    En mémoire : un redémarrage remet les compteurs à zéro, ce qui est
    acceptable pour une application à deux ou trois comptes derrière un
    réseau privé. Le but est de rendre un essai massif impraticable, pas de
    tenir un registre.
    """

    # Au-delà, les adresses dont les échecs sont les plus anciens sont oubliées :
    # la mémoire ne grossit pas avec le nombre d'adresses essayées.
    ADRESSES_MAX = 1000

    def __init__(self, essais_max: int = ESSAIS_MAX, fenetre: float = FENETRE) -> None:
        self.essais_max = essais_max
        self.fenetre = fenetre
        self._echecs: dict[str, deque[float]] = {}
        self._verrou = threading.Lock()

    def _purger(self, adresse: str, instant: float) -> deque[float] | None:
        echecs = self._echecs.get(adresse)
        if echecs is None:
            return None
        while echecs and instant - echecs[0] > self.fenetre:
            echecs.popleft()
        if not echecs:
            # Une adresse sans échec récent n'occupe plus de place.
            del self._echecs[adresse]
            return None
        return echecs

    def bloque(self, adresse: str) -> bool:
        with self._verrou:
            echecs = self._purger(adresse, time.monotonic())
            return echecs is not None and len(echecs) >= self.essais_max

    def echec(self, adresse: str) -> None:
        instant = time.monotonic()
        with self._verrou:
            echecs = self._purger(adresse, instant)
            if echecs is None:
                if len(self._echecs) >= self.ADRESSES_MAX:
                    self._echecs.pop(next(iter(self._echecs)))
                echecs = self._echecs[adresse] = deque()
            echecs.append(instant)

    def reussite(self, adresse: str) -> None:
        with self._verrou:
            self._echecs.pop(adresse, None)


limiteur = Limiteur()
