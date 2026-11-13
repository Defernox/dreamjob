"""Les commandes écrites au bot Telegram : `/profil`, `/excel`, `/candidatures`.

Hébergé, DreamJob n'est joignable que par Tailscale ; le téléphone, lui, a
toujours Telegram. Ces commandes donnent sans ouvrir l'interface ce qu'on lui
demande le plus : retoucher le profil, et récupérer le justificatif France
Travail.

**Seuls les champs simples se règlent ici** — une ligne de texte, un nombre, un
élément ajouté à une liste ou retiré. Expériences, formations et langues sont
des blocs à plusieurs champs : les dicter en une ligne de message ferait plus
d'erreurs que d'économies, et une expérience mal saisie finit dans un CV. Ils
restent à l'interface.

**Une modification passe par la même validation que l'interface** (`ProfilMaj`)
et relance le calcul des notes : le score lit tout le profil.
"""

from __future__ import annotations

import logging
import threading
import unicodedata
from datetime import date

from pydantic import ValidationError
from sqlmodel import Session, select

from ..config import reglages
from ..exports.excel import exporter
from ..models import Offer, Profile, ScoreOffre, Utilisateur
from ..models.base import maintenant
from ..models.enums import CONTRATS, PAYS_FILTRES
from ..schemas.profile import ProfilMaj
from ..scoring.couverture import competences_en_phrases, manques_recurrents
from . import candidatures
from .notification import _telegram
from .scoring import rescorer
from .telegram import appeler, deposer, echapper, ecrire

log = logging.getLogger("dreamjob.commandes")

COMMANDES = [
    ("profil", "Voir ou modifier mon profil"),
    ("excel", "Recevoir le suivi des candidatures (Excel)"),
    ("candidatures", "Mes dernières candidatures"),
    ("motscles", "Les mots-clés de mes offres absents de mon profil"),
    ("aide", "Ce que je sais faire"),
]

# Ce qu'on écrit après /profil → le champ du profil.
SIMPLES = {
    "titre": "titre_vise", "resume": "resume", "situation": "situation_actuelle",
    "disponibilite": "disponibilite", "experience": "annees_experience",
    "prenom": "prenom", "nom": "nom", "email": "email", "telephone": "telephone",
    "ville": "ville", "pays": "pays", "linkedin": "linkedin", "accord": "accord",
}
LISTES = {
    "pays_acceptes": "pays_acceptes", "contrats": "contrats_acceptes",
    "secteurs": "secteurs", "competences": "skills",
}
ALIAS = {"titre_vise": "titre", "situation_actuelle": "situation", "annees_experience": "experience",
         "experiences": "experience", "annees": "experience", "tel": "telephone", "mail": "email",
         "dispo": "disponibilite", "contrats_acceptes": "contrats", "skills": "competences",
         "competence": "competences", "secteur": "secteurs", "contrat": "contrats",
         "pays_accepte": "pays_acceptes"}
VIDER = {"-", "vide", "aucun", "aucune"}

AIDE = (
    "Sous chaque alerte : « Postuler » prépare votre CV et votre lettre, que vous validez "
    "avant tout envoi.\n\n"
    "/profil — voir mon profil\n"
    "/profil disponibilite Immédiate — modifier un champ\n"
    "/profil competences + Python — ajouter à une liste\n"
    "/profil competences - Excel — retirer d'une liste\n"
    "/excel — le suivi des candidatures, pour France Travail\n"
    "/candidatures — mes dix dernières candidatures\n"
    "/motscles — les mots-clés de mes offres vertes absents de mon profil"
)


def annoncer() -> None:
    """Déclare les commandes à Telegram : elles apparaissent dans le menu « / »
    de la conversation. Sans effet si Telegram n'est pas réglé ou ne répond pas."""
    identifiants = _telegram()
    if identifiants is not None:
        appeler(identifiants[0], "setMyCommands",
                {"commands": [{"command": c, "description": d} for c, d in COMMANDES]})


def _cle(texte: str) -> str:
    """« Disponibilité » et « disponibilite » désignent le même champ."""
    sans_accents = "".join(c for c in unicodedata.normalize("NFKD", texte.lower())
                           if not unicodedata.combining(c))
    cle = sans_accents.strip().replace("-", "_").replace(" ", "_")
    return ALIAS.get(cle, cle)


def _canonique(valeur: str, connus: list[str]) -> str | None:
    """« suisse » → « Suisse » : la valeur telle que le vocabulaire l'écrit."""
    return next((c for c in connus if _cle(c) == _cle(valeur)), None)


def _apercu(valeurs: list[str], maximum: int = 12) -> str:
    if not valeurs:
        return "—"
    reste = len(valeurs) - maximum
    return ", ".join(valeurs[:maximum]) + (f" … (+{reste})" if reste > 0 else "")


def resume_profil(profil: Profile) -> str:
    def ligne(nom: str, valeur) -> str:
        return f"<b>{nom}</b> : {echapper(valeur) if valeur not in ('', None) else '—'}"

    lignes = [
        f"👤 <b>{echapper(f'{profil.prenom} {profil.nom}'.strip() or 'Profil')}</b>",
        ligne("titre", profil.titre_vise),
        ligne("situation", profil.situation_actuelle),
        ligne("disponibilite", profil.disponibilite),
        ligne("experience", f"{profil.annees_experience} an(s)" if profil.annees_experience else ""),
        ligne("ville", profil.ville), ligne("pays", profil.pays),
        ligne("telephone", profil.telephone), ligne("email", profil.email),
        ligne("linkedin", profil.linkedin), ligne("accord", profil.accord),
        ligne("contrats", _apercu(list(profil.contrats_acceptes))),
        ligne(f"pays_acceptes ({len(profil.pays_acceptes)})", _apercu(list(profil.pays_acceptes))),
        ligne("secteurs", _apercu(list(profil.secteurs))),
        ligne(f"competences ({len(profil.skills)})", _apercu(profil.noms_skills())),
        ligne("resume", profil.resume[:300] + ("…" if len(profil.resume) > 300 else "")),
        "",
        "Modifier : <code>/profil champ valeur</code> — ex. <code>/profil disponibilite Immédiate</code>",
        "Listes : <code>/profil competences + Python</code> · <code>/profil competences - Excel</code>",
        f"Expériences, formations, langues ({len(profil.experiences)}, {len(profil.formations)}, "
        f"{len(profil.langues)}) : dans l'interface.",
    ]
    if adresse := reglages().adresse_publique:
        lignes.append(f"{adresse.rstrip('/')}/profil")
    return "\n".join(lignes)


class Refus(ValueError):
    """La modification demandée n'est pas applicable ; le message dit pourquoi."""


def _nouvelle_liste(champ: str, actuelle: list, reste: str) -> tuple[list, str]:
    """La liste après « + élément » ou « - élément », et ce qui a été fait."""
    signe, _, element = reste.partition(" ")
    element = element.strip()
    if signe not in ("+", "-") or not element:
        raise Refus("Pour une liste : « + élément » pour ajouter, « - élément » pour retirer.")
    noms = [e.get("nom", "") if isinstance(e, dict) else e for e in actuelle]
    present = next((i for i, n in enumerate(noms) if _cle(n) == _cle(element)), None)
    if signe == "-":
        if present is None:
            raise Refus(f"« {element} » n'est pas dans la liste.")
        return actuelle[:present] + actuelle[present + 1:], f"« {noms[present]} » retiré"
    if present is not None:
        raise Refus(f"« {noms[present]} » est déjà dans la liste.")
    if champ == "pays_acceptes":
        element = _canonique(element, PAYS_FILTRES) or element
        if element not in PAYS_FILTRES:
            raise Refus(f"Pays inconnu : {element}. Les pays proposés sont ceux de l'écran Profil.")
    elif champ == "contrats_acceptes":
        element = _canonique(element, CONTRATS) or element
        if element not in CONTRATS:
            raise Refus(f"Contrat inconnu : {element}. Valeurs : {', '.join(CONTRATS)}.")
    ajout = {"nom": element, "niveau": "", "ancree": False} if champ == "skills" else element
    return actuelle + [ajout], f"« {element} » ajouté"


def modifier(session: Session, profil: Profile, cle: str, reste: str) -> str:
    """Applique « /profil <cle> <reste> ». Rend ce qui a changé, lève `Refus`."""
    cle = _cle(cle)
    if cle not in SIMPLES and cle not in LISTES:
        raise Refus(f"Champ inconnu : {cle}. Champs : {', '.join([*SIMPLES, *LISTES])}.")
    etat = {c: getattr(profil, c) for c in ProfilMaj.model_fields}
    if cle in LISTES:
        champ = LISTES[cle]
        etat[champ], fait = _nouvelle_liste(champ, list(etat[champ] or []), reste.strip())
    else:
        champ = SIMPLES[cle]
        valeur = "" if reste.strip().lower() in VIDER else reste.strip()
        if champ == "annees_experience":
            valeur = valeur or "0"
            if not valeur.isdigit():
                raise Refus("Un nombre d'années est attendu, par exemple : /profil experience 3")
            valeur = int(valeur)
        elif champ == "accord":
            valeur = {"feminin": "feminin", "masculin": "masculin", "": ""}.get(_cle(valeur))
            if valeur is None:
                raise Refus("Accord attendu : masculin, feminin, ou - pour le vider.")
        etat[champ] = valeur
        fait = f"{cle} : {valeur if valeur != '' else '(vide)'}"
    try:
        etat = ProfilMaj.model_validate(etat).model_dump(mode="json")
    except ValidationError as e:
        # Seul le champ touché peut faire refuser : un bloc ancien que le schéma
        # n'accepterait plus ne doit pas interdire de changer une ville.
        fautes = [err["msg"] for err in e.errors() if err["loc"] and err["loc"][0] == champ]
        if fautes:
            raise Refus("Valeur refusée : " + "; ".join(fautes)) from e
    setattr(profil, champ, etat[champ])
    profil.updated_at = maintenant()
    session.add(profil)
    session.commit()
    return fait


def _executer(fonction, *arguments) -> None:
    """Hors du fil de relève. Les tests le remplacent par un appel direct."""
    threading.Thread(target=fonction, args=arguments, name="rescore-telegram", daemon=True).start()


def _profil(session: Session, moi: Utilisateur, arguments: str, jeton: str, conversation: str) -> None:
    profil = session.exec(select(Profile).where(Profile.utilisateur_id == moi.id)).first()
    if profil is None:
        ecrire(jeton, conversation, "Aucun profil pour l'instant : importez votre CV dans l'interface.")
        return
    if not arguments.strip():
        ecrire(jeton, conversation, resume_profil(profil), en_html=True)
        return
    cle, _, reste = arguments.strip().partition(" ")
    if not reste.strip():
        ecrire(jeton, conversation, f"Il manque la valeur : /profil {cle} …  (« - » pour vider)")
        return
    try:
        fait = modifier(session, profil, cle, reste)
    except Refus as e:
        ecrire(jeton, conversation, f"❌ {e}")
        return
    # Le score lit tout le profil : les notes sont recalculées, hors de la relève.
    _executer(rescorer, session.get_bind(), moi.id)
    ecrire(jeton, conversation, f"✅ Profil mis à jour — {fait}.\nLes notes des offres sont recalculées.")


def _excel(session: Session, moi: Utilisateur, jeton: str, conversation: str) -> None:
    lignes = candidatures.lignes_export(session, moi.id)
    if not lignes:
        ecrire(jeton, conversation, "Aucune candidature dans votre suivi pour l'instant.")
        return
    nom = f"candidatures-{date.today().isoformat()}.xlsx"
    pluriel = "s" if len(lignes) > 1 else ""
    if not deposer(jeton, conversation, nom, exporter(lignes),
                   f"{len(lignes)} candidature{pluriel} — justificatif France Travail"):
        ecrire(jeton, conversation, "❌ Le fichier n'a pas pu être déposé ; réessayez dans un instant.")


def _candidatures(session: Session, moi: Utilisateur, jeton: str, conversation: str) -> None:
    lignes = candidatures.lignes_export(session, moi.id)
    if not lignes:
        ecrire(jeton, conversation, "Aucune candidature dans votre suivi pour l'instant.")
        return
    texte = [f"📋 {len(lignes)} candidature{'s' if len(lignes) > 1 else ''} — les dernières :"]
    for ligne in lignes[:10]:
        jour = ligne["date_candidature"].strftime("%d/%m")
        texte.append(f"{jour} · {ligne['statut']} · " +
                     " · ".join(filter(None, [ligne["titre"], ligne["entreprise"]])))
    ecrire(jeton, conversation, "\n".join(texte))


def _motscles(session: Session, moi: Utilisateur, jeton: str, conversation: str) -> None:
    """Ce que les offres vertes du compte demandent et que son profil ne dit pas."""
    profil = session.exec(select(Profile).where(Profile.utilisateur_id == moi.id)).first()
    if profil is None:
        ecrire(jeton, conversation, "Aucun profil pour l'instant : importez votre CV dans l'interface.")
        return
    seuil = reglages().scoring.seuils.bon
    vertes = list(session.exec(
        select(Offer).join(ScoreOffre, ScoreOffre.offer_id == Offer.id)
        .where(ScoreOffre.utilisateur_id == moi.id, ScoreOffre.score >= seuil)).all())
    if not vertes:
        ecrire(jeton, conversation, "Aucune offre verte pour l'instant : rien à comparer.")
        return
    manques = manques_recurrents(profil, vertes)
    lignes = [f"🔎 <b>Mots-clés de vos {len(vertes)} offres vertes absents de votre profil</b>"]
    if manques:
        lignes += [f"• {echapper(terme)} — {nombre} offres" for terme, nombre in manques]
        lignes += ["", "Un recruteur cherche dans son logiciel avec ces mots. <b>N'ajoutez que ce "
                       "que vous avez réellement pratiqué</b> :",
                   f"<code>/profil competences + {echapper(manques[0][0].capitalize())}</code>"]
    else:
        lignes.append("Rien d'important : votre profil dit déjà les mots de vos offres.")
    if phrases := competences_en_phrases(profil):
        lignes += ["", f"⚠️ {len(phrases)} de vos {len(profil.skills)} compétences sont des phrases "
                       f"(« {echapper(phrases[0])} ») : un logiciel de recrutement range des mots — "
                       "« Excel », « VBA », « Reporting ». Découpez-les en compétences courtes."]
    ecrire(jeton, conversation, "\n".join(lignes), en_html=True)


def traiter(session: Session, courrier: dict, jeton: str, conversation: str) -> None:
    """Un message écrit au bot par le propriétaire (l'appelant l'a vérifié)."""
    texte = (courrier.get("text") or "").strip()
    if not texte:
        return
    moi = session.exec(select(Utilisateur).where(Utilisateur.proprietaire == True)).first()  # noqa: E712
    if moi is None:
        return
    commande, _, arguments = texte.partition(" ")
    # Dans un groupe, Telegram écrit « /profil@NomDuBot ».
    commande = commande.split("@", 1)[0].lower()
    if commande == "/profil":
        _profil(session, moi, arguments, jeton, conversation)
    elif commande == "/excel":
        _excel(session, moi, jeton, conversation)
    elif commande == "/candidatures":
        _candidatures(session, moi, jeton, conversation)
    elif commande == "/motscles":
        _motscles(session, moi, jeton, conversation)
    else:
        ecrire(jeton, conversation, AIDE)
