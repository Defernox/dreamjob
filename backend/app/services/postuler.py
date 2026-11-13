"""Postuler depuis Telegram : « Postuler ? » sous l'alerte, et la suite.

L'alerte ne demande plus un avis mais une décision. Oui : DreamJob écrit le CV
ciblé et la lettre, les dépose dans la conversation, et attend. Rien ne part
sans un second appui — le candidat relit ce qui portera son nom.

Ce second appui dépend de l'annonce (`courriel.py`) :

- **elle donne une adresse de candidature**, et la boîte d'envoi est réglée :
  « Envoyer » fait partir l'e-mail, CV et lettre joints, et note la candidature ;
- **sinon**, elle se postule sur un site. DreamJob ne remplit pas le formulaire
  d'un employeur à la place du candidat ; il prépare tout ce qui peut l'être —
  les deux PDF, le lien, les coordonnées et la lettre à copier — et « C'est
  envoyé » note la candidature.

**Les boutons portent tout l'état** (`post:<offre>:<action>`) : le dossier se
retrouve par l'offre, le mode d'envoi se recalcule de l'annonce. Aucune table,
aucune mémoire à perdre au redémarrage du serveur.

**La génération tourne dans son propre fil.** Elle dure une minute ; la relève
des réponses (`avis.py`) doit rester libre d'accuser les autres appuis. Une
seule à la fois : LibreOffice ne se partage pas, et deux appuis impatients ne
doivent pas payer deux dossiers.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from fastapi import HTTPException
from sqlmodel import Session, select

from ..documents import ats, lecture_ats
from ..documents.correspondance import correspondance_ats
from ..documents.dossier import JOURNAL, noms_de_fichiers
from ..models import Offer, Profile, ScoreOffre, Utilisateur
from . import candidatures, courriel
from .notification import PREFIXE_POSTULER, boutons_postuler
from .telegram import SANS_CLAVIER, accuser, changer_clavier, deposer, echapper, ecrire

log = logging.getLogger("dreamjob.postuler")

OUI, NON = "oui", "non"
ENVOYER, FAIT, REFAIRE, ANNULER, COPIER = "env", "fait", "ref", "ann", "txt"
ACTIONS = {OUI, NON, ENVOYER, FAIT, REFAIRE, ANNULER, COPIER}

MAX_AVERTISSEMENTS = 5

_occupees: set[int] = set()            # offres dont le dossier ou l'envoi est en cours
_verrou = threading.Lock()
_une_generation = threading.Lock()


def lire(donnees: str) -> tuple[int, str] | None:
    """(offre, action) depuis « post:<offre>:<action> », sinon None."""
    morceaux = (donnees or "").split(":")
    if len(morceaux) != 3 or morceaux[0] != PREFIXE_POSTULER or morceaux[2] not in ACTIONS:
        return None
    try:
        return int(morceaux[1]), morceaux[2]
    except ValueError:
        return None


def _executer(fonction, *arguments) -> None:
    """Hors du fil de relève. Les tests le remplacent par un appel direct."""
    threading.Thread(target=fonction, args=arguments, name="dossier-telegram", daemon=True).start()


def _reserver(offre_id: int) -> bool:
    with _verrou:
        if offre_id in _occupees:
            return False
        _occupees.add(offre_id)
        return True


def _liberer(offre_id: int) -> None:
    with _verrou:
        _occupees.discard(offre_id)


def _proprietaire(session: Session) -> Utilisateur | None:
    return session.exec(select(Utilisateur).where(Utilisateur.proprietaire == True)).first()  # noqa: E712


def _clavier_coche(message: dict, offre_id: int, choix: str) -> dict:
    """Le clavier de l'alerte, la ligne « Postuler ? » cochée ; le lien vers la
    fiche reste tel quel."""
    lignes = (message.get("reply_markup") or {}).get("inline_keyboard") or []
    gardees = [l for l in lignes
               if not any(str(b.get("callback_data", "")).startswith(f"{PREFIXE_POSTULER}:") for b in l)]
    return {"inline_keyboard": gardees + [boutons_postuler(offre_id, choix)]}


def _bouton(texte: str, offre_id: int, action: str) -> dict:
    return {"text": texte, "callback_data": f"{PREFIXE_POSTULER}:{offre_id}:{action}"}


def _nom(offre: Offer) -> str:
    return " · ".join(filter(None, [offre.titre, offre.entreprise]))


def pieces(dossier: Path, profil: Profile) -> tuple[Path | None, Path | None]:
    """(CV, lettre) du dossier — en PDF, sinon en Word quand LibreOffice n'a
    pas pu convertir. None pour ce qui manque : le garde-fou de la lettre a le
    droit de ne rien livrer."""
    def trouve(nom: str) -> Path | None:
        for extension in (".pdf", ".docx"):
            if (dossier / f"{nom}{extension}").is_file():
                return dossier / f"{nom}{extension}"
        return None

    nom_cv, nom_lettre = noms_de_fichiers(profil)
    return trouve(nom_cv), trouve(nom_lettre)


def _cout(dossier: Path) -> str:
    """« 0,08 $ », lu dans le journal du dossier ; vide si rien n'a été payé."""
    try:
        cout = json.loads((dossier / JOURNAL).read_text(encoding="utf-8")).get("cout_usd") or 0
    except (OSError, ValueError):
        return ""
    return f"{cout:.2f} $".replace(".", ",") if cout else ""


def _dossier(session: Session, offre: Offer, moi: Utilisateur) -> Path | None:
    from ..api.documents import _dossier_de      # import tardif : l'API importe les services
    return _dossier_de(offre, session, moi)


def exigences_a_risque(profil: Profile, offre: Offer) -> list[str]:
    """Ce que l'annonce exige et que le profil n'atteint pas — la matière des
    questions éliminatoires d'un formulaire. Le candidat y répondra lui-même :
    autant qu'il les voie venir."""
    lu = correspondance_ats(profil, offre)
    risques = []
    exigees, acquises = lu.get("annees_exigees"), lu.get("annees_profil")
    if exigees and acquises and exigees > acquises:
        risques.append(f"{exigees} ans d'expérience demandés (profil : {acquises})")
    parlees = set(profil.codes_langues())
    manquantes = [code for code in lu.get("langues_exigees") or [] if code not in parlees]
    if manquantes and parlees:
        risques.append("langue exigée absente du profil : " + ", ".join(manquantes))
    return risques


def _lignes_ats(profil: Profile, offre: Offer, lecture: dict | None) -> list[str]:
    """Ce que le logiciel de recrutement fera de ce dossier, en quelques lignes."""
    lignes = []
    if resume := lecture_ats.resume(lecture or {}):
        lignes.append(f"🤖 {echapper(resume)}")
        autrement = ((lecture or {}).get("termes") or {}).get("dit_autrement") or []
        if autrement:
            lignes.append("Mots de l'annonce que votre CV dit autrement : "
                          + echapper(", ".join(autrement)))
    if risques := exigences_a_risque(profil, offre):
        lignes.append("⚠️ Questions éliminatoires possibles — " + echapper(" ; ".join(risques)))
    if fiche := ats.fiche_de(offre):
        lignes.append(f"🏢 <b>{echapper(fiche.nom)}</b> — {echapper(fiche.conseil)}")
    return lignes


def _proposer(session: Session, moi: Utilisateur, offre: Offer, dossier: Path,
              avertissements: list[str], jeton: str, conversation: str,
              lecture: dict | None = None) -> None:
    """Dépose les documents puis demande la validation, avec les boutons que
    l'annonce permet."""
    profil = session.exec(select(Profile).where(Profile.utilisateur_id == moi.id)).first()
    cv, lettre = pieces(dossier, profil)
    for piece, legende in ((cv, "CV"), (lettre, "Lettre de motivation")):
        if piece is not None:
            deposer(jeton, conversation, piece.name, piece.read_bytes(), f"{legende} — {_nom(offre)}")
    # Un logiciel réputé mieux lire le Word que le PDF : on donne aussi le Word.
    fiche = ats.fiche_de(offre)
    if fiche and fiche.format == "docx" and cv is not None and cv.suffix == ".pdf":
        word = cv.with_suffix(".docx")
        if word.is_file():
            deposer(jeton, conversation, word.name, word.read_bytes(),
                    f"CV en Word, à joindre de préférence sur {fiche.nom}")

    lignes = [f"📄 <b>Dossier prêt</b> — {echapper(_nom(offre))}"]
    if cout := _cout(dossier):
        lignes.append(f"Coût de rédaction : {cout}")
    lignes += [f"⚠️ {echapper(a)}" for a in avertissements[:MAX_AVERTISSEMENTS]]
    lignes += _lignes_ats(profil, offre, lecture)

    adresse = courriel.adresse_de_candidature(offre)
    page = courriel.page_de_candidature(offre)
    refaire = [_bouton("🔁 Refaire", offre.id, REFAIRE), _bouton("❌ Annuler", offre.id, ANNULER)]
    clavier: list[list[dict]] = []
    if adresse and courriel.boite() and cv and lettre:
        lignes.append(f"\n📧 L'annonce demande d'écrire à <code>{echapper(adresse)}</code>. "
                      "Relisez les deux documents : « Envoyer » fait partir l'e-mail avec eux.")
        clavier.append([_bouton("✅ Envoyer ma candidature", offre.id, ENVOYER)])
    else:
        if adresse and not courriel.boite():
            lignes.append(f"\n📧 L'annonce donne une adresse : <code>{echapper(adresse)}</code> — "
                          "l'envoi automatique n'est pas réglé (SMTP, voir le guide de déploiement).")
        elif adresse:
            lignes.append(f"\n📧 L'annonce donne une adresse : <code>{echapper(adresse)}</code> — "
                          "il manque un document, rien ne partira automatiquement.")
        lignes.append("\n🌐 Cette offre se postule sur le site : ouvrez la page, joignez les "
                      "documents ci-dessus, puis appuyez sur « C'est envoyé ».")
        if page:
            clavier.append([{"text": "🌐 Ouvrir la page de candidature", "url": page}])
        clavier.append([_bouton("📋 Coordonnées et lettre à copier", offre.id, COPIER)])
        clavier.append([_bouton("✅ C'est envoyé", offre.id, FAIT)])
    clavier.append(refaire)
    ecrire(jeton, conversation, "\n".join(lignes), clavier=clavier, en_html=True)


def preparer(moteur, offre_id: int, jeton: str, conversation: str) -> None:
    """Écrit le dossier d'une offre et le propose. Ne lève jamais : une panne se
    dit dans la conversation, avec de quoi réessayer."""
    from ..api.documents import generer_documents    # import tardif, voir _dossier

    reessayer = [[_bouton("🔁 Réessayer", offre_id, REFAIRE), _bouton("❌ Annuler", offre_id, ANNULER)]]
    try:
        with _une_generation, Session(moteur) as session:
            moi = _proprietaire(session)
            offre = session.get(Offer, offre_id)
            if moi is None or offre is None:
                ecrire(jeton, conversation, "Offre introuvable.")
                return
            try:
                # La génération de l'interface, telle quelle : budget, garde-fou
                # de la lettre, coût consigné, dossier rattaché à la candidature.
                resultat = generer_documents(offre_id, ouvrir_dossier=False, session=session, moi=moi)
            except HTTPException as e:
                ecrire(jeton, conversation, f"❌ Documents non générés pour {_nom(offre)} — {e.detail}",
                       clavier=reessayer)
                return
            _proposer(session, moi, offre, Path(resultat.dossier), list(resultat.avertissements),
                      jeton, conversation, lecture=resultat.lecture_ats)
    except Exception:  # noqa: BLE001 — le fil ne doit pas mourir en silence
        log.exception("Dossier de l'offre %s non préparé", offre_id)
        ecrire(jeton, conversation, "❌ Documents non générés : une erreur inattendue, consignée "
               "dans les journaux du serveur.", clavier=reessayer)
    finally:
        _liberer(offre_id)


def _envoyer(session: Session, moi: Utilisateur, offre: Offer, jeton: str, conversation: str,
             rappel: dict) -> bool:
    """L'e-mail de candidature. Vrai s'il est parti et noté."""
    adresse, envoi = courriel.adresse_de_candidature(offre), courriel.boite()
    dossier = _dossier(session, offre, moi)
    profil = session.exec(select(Profile).where(Profile.utilisateur_id == moi.id)).first()
    cv, lettre = pieces(dossier, profil) if dossier and profil else (None, None)
    if not (adresse and envoi and cv and lettre):
        accuser(jeton, rappel, "Envoi impossible : refaites les documents.")
        return False
    accuser(jeton, rappel, "Envoi en cours…")
    try:
        courriel.envoyer(courriel.composer(profil, offre, adresse, [cv, lettre], envoi), envoi)
    except courriel.CourrielErreur as e:
        ecrire(jeton, conversation, f"❌ L'e-mail n'est pas parti : {e}. Rien n'est noté dans le "
               "suivi ; vérifiez vos messages envoyés avant de réessayer.")
        return False
    candidatures.enregistrer(
        session, moi.id, offre.id, contact=adresse, dossier=str(dossier),
        notes=f"Envoyée par e-mail par DreamJob le {candidatures.horodatage()}.")
    changer_clavier(jeton, conversation, rappel.get("message") or {}, SANS_CLAVIER)
    ecrire(jeton, conversation, f"✅ Candidature envoyée à {adresse} — {_nom(offre)}.\n"
           "Une copie vous est adressée, et elle est notée dans votre suivi (/excel).")
    return True


def _a_copier(session: Session, moi: Utilisateur, offre: Offer, jeton: str, conversation: str) -> None:
    """Ce qu'un formulaire redemande toujours : un appui sur une ligne la copie."""
    profil = session.exec(select(Profile).where(Profile.utilisateur_id == moi.id)).first()
    if profil is None:
        return
    champs = [f"{profil.prenom} {profil.nom}".strip(), profil.prenom, profil.nom, profil.email,
              profil.telephone, profil.ville, profil.linkedin]
    lignes = ["📋 <b>À copier</b> (un appui sur une ligne la copie)"]
    lignes += [f"<code>{echapper(c)}</code>" for c in dict.fromkeys(champs) if c]
    ecrire(jeton, conversation, "\n".join(lignes), en_html=True)

    dossier = _dossier(session, offre, moi)
    lettre = pieces(dossier, profil)[1] if dossier else None
    docx = lettre.with_suffix(".docx") if lettre else None
    if docx is None or not docx.is_file():
        return
    try:
        from docx import Document
        texte = "\n\n".join(p.text.strip() for p in Document(str(docx)).paragraphs if p.text.strip())
    except Exception:  # noqa: BLE001 — un Word illisible ne vaut pas une erreur
        log.warning("Lettre illisible pour la copie (%s).", docx.name)
        return
    if texte:
        ecrire(jeton, conversation, texte)


def traiter(session: Session, rappel: dict, jeton: str, conversation: str) -> bool:
    """Un appui sur un bouton « post:… ». Vrai si un avis a été enregistré."""
    from . import avis      # import tardif : avis.py aiguille vers ce module

    lu = lire(rappel.get("data", ""))
    moi = _proprietaire(session)
    offre = session.get(Offer, lu[0]) if lu else None
    if lu is None or moi is None or offre is None or session.get(ScoreOffre, (moi.id, offre.id)) is None:
        # Une offre hors du fil du propriétaire n'est jamais touchée.
        accuser(jeton, rappel, "Offre introuvable." if lu else "")
        return False
    offre_id, action = lu
    message = rappel.get("message") or {}

    if action == NON:
        avis.enregistrer(session, offre_id, 0)
        accuser(jeton, rappel, "Noté : on passe.")
        changer_clavier(jeton, conversation, message, _clavier_coche(message, offre_id, NON))
        return True

    if action in (OUI, REFAIRE):
        note = avis.enregistrer(session, offre_id, 1) if action == OUI else False
        if action == OUI and candidatures.de(session, moi.id, offre_id) is not None:
            accuser(jeton, rappel, "Vous avez déjà postulé à cette offre.")
            return note
        if not _reserver(offre_id):
            accuser(jeton, rappel, "Les documents sont déjà en préparation.")
            return note
        accuser(jeton, rappel, "Je prépare votre CV et votre lettre : une minute environ.")
        changer_clavier(jeton, conversation, message,
                        _clavier_coche(message, offre_id, OUI) if action == OUI else SANS_CLAVIER)
        _executer(preparer, session.get_bind(), offre_id, jeton, conversation)
        return note

    if action == ANNULER:
        accuser(jeton, rappel, "Annulé.")
        changer_clavier(jeton, conversation, message, SANS_CLAVIER)
        ecrire(jeton, conversation, f"❌ Candidature annulée — {_nom(offre)}. Rien n'a été envoyé.")
        return False

    if action == COPIER:
        accuser(jeton, rappel)
        _a_copier(session, moi, offre, jeton, conversation)
        return False

    # Envoyer ou « C'est envoyé » : une candidature ne se note qu'une fois.
    if candidatures.de(session, moi.id, offre_id) is not None:
        accuser(jeton, rappel, "Cette candidature est déjà notée dans votre suivi.")
        changer_clavier(jeton, conversation, message, SANS_CLAVIER)
        return False
    if not _reserver(offre_id):
        accuser(jeton, rappel, "Déjà en cours…")
        return False
    try:
        if action == ENVOYER:
            _envoyer(session, moi, offre, jeton, conversation, rappel)
        else:
            dossier = _dossier(session, offre, moi)
            candidatures.enregistrer(
                session, moi.id, offre_id, dossier=str(dossier or ""),
                notes=f"Déposée sur le site le {candidatures.horodatage()}, documents préparés "
                      "par DreamJob.")
            accuser(jeton, rappel, "Noté dans votre suivi.")
            changer_clavier(jeton, conversation, message, SANS_CLAVIER)
            ecrire(jeton, conversation, f"✅ Candidature notée — {_nom(offre)}.\n"
                   "Elle figure dans votre suivi (/excel).")
    finally:
        _liberer(offre_id)
    return False
