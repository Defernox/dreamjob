"""Postuler par e-mail : la seule candidature qu'on puisse envoyer proprement à
la place du candidat.

Un formulaire de recrutement demande un compte, des cases de consentement, des
questions auxquelles seul le candidat peut répondre, souvent un test anti-robot :
le remplir par script serait fragile, et contourner une protection est exclu
(voir « Sites des employeurs » dans CLAUDE.md). Une adresse de candidature, elle,
attend exactement ce que DreamJob sait produire — un message, un CV, une lettre.

**L'adresse ne se devine pas.** Elle vient du champ de contact de l'annonce
(France Travail), ou du texte quand il invite à y écrire (« envoyez votre CV
à… »). Une adresse citée sans cette invitation — le délégué à la protection des
données, la mission handicap — n'est pas une adresse de candidature. Et le
candidat la voit avant de valider : rien ne part sans son appui.

**La boîte d'envoi est la sienne** (`SMTP_*` dans `.env`) : le recruteur répond
à une vraie adresse, et le message figure dans ses « envoyés ». Une copie cachée
lui revient — c'est la preuve d'envoi, pour France Travail comme pour lui.

**Le corps du message est fixe.** Trois phrases écrites ici, en français ou en
anglais selon l'annonce : aucun appel au modèle, donc rien à inventer. Ce qui
est personnel est dans la lettre jointe, déjà passée par le garde-fou.
"""

from __future__ import annotations

import logging
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from ..config import reglages
from ..documents.intitule import nettoyer_intitule
from ..models import Offer, Profile
from ..scoring.langue import detecter

log = logging.getLogger("dreamjob.courriel")

_ADRESSE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# Ce qui, avant une adresse, dit qu'on y envoie sa candidature.
_INVITATION = re.compile(
    r"candidat|postul|\bcv\b|curriculum|envoy|adress|transmett|"
    r"\bapply|application|r[ée]sum[ée]|\bsend\b|bewerbung", re.IGNORECASE)
PORTEE_INVITATION = 200      # caractères lus avant l'adresse
# Des boîtes auxquelles on n'envoie jamais un CV, même invité.
_BOITES_ECARTEES = ("noreply", "no-reply", "no_reply", "donotreply", "ne-pas-repondre", "nepasrepondre",
                    "dpo", "rgpd", "gdpr", "privacy", "dataprotection", "donnees", "handicap",
                    "abuse", "unsubscribe", "desinscription")

DELAI = 30.0


class CourrielErreur(RuntimeError):
    """L'e-mail n'est pas parti. Le message dit pourquoi, en français."""


@dataclass(frozen=True)
class Boite:
    hote: str
    port: int
    utilisateur: str
    mot_de_passe: str
    expediteur: str


def boite() -> Boite | None:
    """La boîte d'envoi du propriétaire, si `.env` la décrit en entier."""
    r = reglages()
    hote, utilisateur, mot_de_passe = (r.secret("SMTP_HOTE"), r.secret("SMTP_UTILISATEUR"),
                                       r.secret("SMTP_MOT_DE_PASSE"))
    if not (hote and utilisateur and mot_de_passe):
        return None
    try:
        port = int(r.secret("SMTP_PORT") or 587)
    except ValueError:
        port = 587
    return Boite(hote.strip(), port, utilisateur.strip(),
                 # Google affiche ses mots de passe d'application par blocs de
                 # quatre séparés d'espaces : collés tels quels, ils échouaient.
                 mot_de_passe.replace(" ", ""),
                 (r.secret("SMTP_EXPEDITEUR") or utilisateur).strip())


def _acceptable(adresse: str) -> bool:
    locale = adresse.split("@", 1)[0].lower()
    return not any(mot in locale for mot in _BOITES_ECARTEES)


def adresse_de_candidature(offre: Offer) -> str:
    """L'adresse à laquelle l'annonce demande d'écrire, ou « »."""
    contact = (offre.raw or {}).get("contact") if isinstance(offre.raw, dict) else None
    if isinstance(contact, dict):
        # France Travail : le champ contient parfois une phrase ou un lien —
        # seule une vraie adresse compte.
        trouvee = _ADRESSE.search(str(contact.get("courriel") or ""))
        if trouvee and _acceptable(trouvee.group()):
            return trouvee.group()
    texte = offre.description_brute or ""
    for trouvee in _ADRESSE.finditer(texte):
        avant = texte[max(0, trouvee.start() - PORTEE_INVITATION):trouvee.start()]
        if _INVITATION.search(avant) and _acceptable(trouvee.group()):
            return trouvee.group().rstrip(".")
    return ""


def page_de_candidature(offre: Offer) -> str:
    """Où postuler quand l'annonce ne donne pas d'adresse : le lien de
    candidature qu'elle fournit, sinon l'annonce elle-même."""
    contact = (offre.raw or {}).get("contact") if isinstance(offre.raw, dict) else None
    if isinstance(contact, dict):
        lien = str(contact.get("urlPostulation") or "").strip()
        if lien.lower().startswith(("http://", "https://")):
            return lien
    return offre.url or ""


def _textes(profil: Profile, offre: Offer) -> tuple[str, str]:
    """(objet, corps) du message, dans la langue de l'annonce."""
    intitule = nettoyer_intitule(offre.titre, offre.lieu) or offre.titre
    nom = f"{profil.prenom} {profil.nom}".strip()
    signature = "\n".join(filter(None, [nom, profil.telephone, profil.email, profil.linkedin]))
    reference = (f" (offre n° {offre.source_id})"
                 if offre.source == "france_travail" and offre.source_id else "")
    if detecter(offre.description_brute, defaut="fr") == "en":
        objet = f"Application – {intitule} – {nom}"
        corps = (f"Dear Sir or Madam,\n\n"
                 f"Please find attached my CV and cover letter in application for the position "
                 f"of {intitule}.\n\n"
                 f"I remain at your disposal for an interview.\n\n"
                 f"Kind regards,\n\n{signature}\n")
    else:
        objet = f"Candidature – {intitule}{reference} – {nom}"
        corps = (f"Madame, Monsieur,\n\n"
                 f"Je vous adresse ma candidature au poste de {intitule}{reference}. "
                 f"Vous trouverez ci-joint mon CV et ma lettre de motivation.\n\n"
                 f"Je reste à votre disposition pour un entretien.\n\n"
                 f"Cordialement,\n\n{signature}\n")
    return objet, corps


def composer(profil: Profile, offre: Offer, destinataire: str, pieces: list[Path],
             envoi: Boite) -> EmailMessage:
    objet, corps = _textes(profil, offre)
    message = EmailMessage()
    message["From"] = formataddr((f"{profil.prenom} {profil.nom}".strip(), envoi.expediteur))
    message["To"] = destinataire
    message["Subject"] = objet
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=envoi.expediteur.rsplit("@", 1)[-1])
    # Le recruteur doit répondre à l'adresse du CV, pas à celle d'une boîte
    # d'envoi qui en différerait.
    if profil.email and profil.email.strip().lower() != envoi.expediteur.lower():
        message["Reply-To"] = profil.email.strip()
    message.set_content(corps)
    for piece in pieces:
        sous_type = "pdf" if piece.suffix.lower() == ".pdf" else "octet-stream"
        message.add_attachment(piece.read_bytes(), maintype="application", subtype=sous_type,
                               filename=piece.name)
    return message


def envoyer(message: EmailMessage, envoi: Boite) -> None:
    """Remet le message au serveur d'envoi, copie cachée à l'expéditeur.

    Lève `CourrielErreur` si le serveur ne l'a pas accepté. Un refus du seul
    destinataire est une erreur aussi : la copie partie chez soi ne vaut pas
    candidature."""
    destinataire = message["To"]
    contexte = ssl.create_default_context()
    try:
        if envoi.port == 465:
            serveur = smtplib.SMTP_SSL(envoi.hote, envoi.port, timeout=DELAI, context=contexte)
        else:
            serveur = smtplib.SMTP(envoi.hote, envoi.port, timeout=DELAI)
        with serveur:
            if envoi.port != 465:
                serveur.starttls(context=contexte)
            serveur.login(envoi.utilisateur, envoi.mot_de_passe)
            refuses = serveur.send_message(message, to_addrs=[destinataire, envoi.expediteur])
    except smtplib.SMTPAuthenticationError as e:
        raise CourrielErreur(
            "la boîte d'envoi a refusé l'identifiant ou le mot de passe (SMTP_UTILISATEUR, "
            "SMTP_MOT_DE_PASSE) — avec Gmail, il faut un « mot de passe d'application »") from e
    except smtplib.SMTPRecipientsRefused as e:
        raise CourrielErreur(f"l'adresse {destinataire} a été refusée par le serveur") from e
    except (smtplib.SMTPException, OSError) as e:
        raise CourrielErreur(f"le serveur d'envoi {envoi.hote} n'a pas accepté le message "
                             f"({type(e).__name__})") from e
    if destinataire in (refuses or {}):
        raise CourrielErreur(f"l'adresse {destinataire} a été refusée par le serveur")
    log.info("Candidature envoyée par e-mail (%s).", message["Subject"])
