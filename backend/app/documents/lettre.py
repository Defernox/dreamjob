"""Lettre de motivation : les prompts et la boucle de génération.

**Règle non négociable du projet : le LLM n'invente rien.** Aucune expérience,
aucun diplôme, aucune entreprise absente du profil ne doit apparaître.

La contrainte est posée dans le prompt système, mais un prompt n'est pas une
garantie — surtout avec un modèle local. Chaque lettre est **vérifiée** par
`controles.py`, puis régénérée en nommant la faute au modèle. Nommer la faute
est ce qui marche : lui demander de se relire, non (mesuré, cf. `relire`).

**Deux familles de fautes, deux traitements**, détaillés dans `controles.py` :
les fautes d'honnêteté refusent la lettre, les fautes de style la font
seulement retenter, puis sont signalées à l'utilisateur. Refuser une lettre
exacte pour un « relever les défis » serait disproportionné.
"""

from __future__ import annotations

import logging
import re

from ..models import Offer, Profile
from ..scoring.texte import normaliser
from .controles import (  # ré-exportés : l'API publique des contrôles passe par ici
    LONGUEUR_COPIE,
    bloquantes,
    chiffres_inventes,
    cliches,
    contrat_incoherent,
    disponibilite_inventee,
    copies_de_l_offre,
    defauts_de_style,
    entites_suspectes,
    ouverture_convenue,
    rythme_mecanique,
    voix_incorrecte,
)
from .exemples import EXEMPLES_STYLE_COURT

log = logging.getLogger("dreamjob.lettre")

MOTS_MAX = 340
MOTS_MIN = 90

PROMPT_SYSTEME = """Tu ES le candidat. Tu écris TA propre lettre de motivation, en français.

QUI PARLE — LA RÈGLE LA PLUS IMPORTANTE
Tu écris à la première personne du singulier : « je », « mon », « ma », « mes ».
« vous » et « votre » désignent TOUJOURS l'entreprise qui recrute — jamais toi.
Tu ne décris JAMAIS ton propre parcours avec « vous » ou « votre » : ce parcours
est le tien, tu dis « mon expérience », jamais « votre expérience ».
Tu postules : tu demandes le poste, tu ne le proposes pas et tu ne recrutes
personne.
Le PROFIL ci-dessous parle de toi à la troisième personne (« ses compétences ») :
c'est une fiche de renseignement, pas ton style. Reprends-en le contenu et
écris-le à la première personne.

INTERDIT ABSOLU — TU N'INVENTES RIEN.
Tu ne mentionnes aucune entreprise, école, diplôme, certification, technologie,
ville, date ni CHIFFRE qui ne figure pas dans le PROFIL ou dans l'OFFRE
ci-dessous. Si une information te manque, tu écris la lettre sans elle.
N'affirme jamais avoir étudié ou travaillé quelque part sans que ce soit écrit.

TU NE RECOPIES PAS L'ANNONCE.
Reprendre une phrase de l'offre revient à s'attribuer une compétence que le
profil ne mentionne pas — et le recruteur reconnaît son propre texte. Dis avec
tes mots ce que TON parcours apporte à ce poste.

TU EMPLOIES LE BON CONTRAT.
Celui de l'offre, et lui seul. Si l'offre porte sur un CDI, les mots
« alternance », « apprentissage » et « stage » n'ont rien à y faire.

FORME
- Exactement quatre paragraphes, 300 à 340 mots au total.
- Ne redonne pas ton nom : il figure déjà en en-tête de la lettre.
- P1 : ta situation actuelle et le poste visé, nommé exactement. Une accroche
  factuelle, pas une déclaration d'intérêt. Tu ne commences JAMAIS par
  « C'est avec », « Actuellement », « Fort de », « Passionné par », « Suite à »,
  « Je me permets » ni « Veuillez trouver ».
- P2 : UNE expérience, développée. Chiffres, périmètre, décisions prises. Pas
  d'énumération de qualités : on les déduit des faits.
- P3 : le lien avec CETTE offre. Nomme au moins deux éléments propres à
  l'annonce — un outil, une mission, une contrainte — mais AVEC TES MOTS : ne
  recopie pas ses phrases. Une lettre qui pourrait partir chez un concurrent
  est un échec.
- P4 : disponibilité et clôture, deux phrases au plus. N'annonce une
  disponibilité que si le profil en indique une.

RYTHME
- Chaque paragraphe contient au moins une phrase de moins de douze mots.
- Jamais trois phrases de suite de longueur voisine.
- Aucune énumération de trois adjectifs.

TON
Sobre. Tu exposes des faits et tu laisses le lecteur en tirer les conclusions.
Aucun superlatif sur l'entreprise, aucune auto-évaluation (« je suis rigoureux »),
aucune déférence excessive.
N'accorde aucun adjectif à ton propre genre — il n'est pas connu. Écris « ce
poste m'intéresse » plutôt que « je suis ravi » ou « je suis heureuse ».

Rends uniquement le corps de la lettre : ni en-tête, ni adresse, ni date, ni
objet, ni formule d'appel, ni formule de politesse finale, ni signature. Ces
éléments sont ajoutés automatiquement après toi."""

PROMPT_RELECTURE = """Tu relis une lettre de motivation et tu la réécris, en français.

CE QUE TU CHASSES
- Les formules toutes faites : « fort de mon expérience », « je suis convaincu
  que », « n'hésitez pas à », « dynamique et motivé », « j'attends avec
  impatience ».
- Les phrases interchangeables. Une phrase qui resterait vraie en changeant le
  nom de l'entreprise ne dit rien : rends-la précise, ou supprime-la.
- Le rythme mécanique. Des phrases toutes de la même longueur se lisent comme un
  formulaire. Alterne les courtes et les longues.
- Les enfilades (« En outre… De plus… Également… ») : relie les faits au lieu de
  les empiler.

CE QUE TU NE TOUCHES PAS
- Les faits. Tu n'ajoutes AUCUN nom, chiffre, date, entreprise, école ni
  compétence qui ne soit déjà dans le brouillon. Tu peux en retirer, jamais en
  inventer — c'est la règle absolue.
- La voix : première personne du singulier ; « vous » désigne l'entreprise qui
  recrute, jamais le candidat.
- La structure : quatre paragraphes, et la même longueur d'ensemble.

Supprime plutôt que de remplacer : une lettre de 300 mots dense vaut mieux
qu'une lettre de 340 dont 40 sont du remplissage.

Rends uniquement la lettre réécrite, sans commentaire ni explication."""

# Formules d'appel et de politesse : le modèle en ajoute malgré la consigne, et
# le document les met en page lui-même. On les retire plutôt que de rejeter.
_APPEL = re.compile(
    # « Mon cher directeur, » et « Salutations cher recruteur, » passaient au
    # travers : le modèle invente des formules d'appel que la consigne interdit.
    r"^\s*(?:mon\s+|ma\s+)?"
    r"(?:bonjour|salutations?|cher|chère|chere|madame|monsieur|mesdames|messieurs)"
    r"[^\n]{0,60}[,:]\s*",
    re.IGNORECASE,
)
# Le modèle produit parfois un objet malgré la consigne, et le document en pose
# un lui-même : les deux se retrouveraient l'un sous l'autre.
_OBJET = re.compile(r"^\s*objet\s*[:–-][^\n]*\n+", re.IGNORECASE)

_FORMULES_FINALES = (
    "cordialement", "sincerement", "respectueusement",
    "veuillez agreer", "veuillez recevoir", "je vous prie d agreer",
    "je vous prie de recevoir", "dans l attente", "dans cette attente",
    "en vous remerciant", "restant a votre disposition",
)


def _est_formule_finale(texte: str) -> bool:
    debut = normaliser(texte)
    return any(debut.startswith(normaliser(f)) for f in _FORMULES_FINALES)


def _retirer_signature(paragraphes: list[str], profil: Profile | None) -> list[str]:
    """Retire le nom du candidat s'il termine la lettre.

    Le modèle signe malgré la consigne, et le document appose déjà une
    signature : les deux se retrouvaient l'une sous l'autre.
    """
    if profil is None or not (profil.prenom or profil.nom):
        return paragraphes
    nom = normaliser(f"{profil.prenom} {profil.nom}")
    while len(paragraphes) > 1 and normaliser(paragraphes[-1]) == nom:
        paragraphes.pop()
    return paragraphes


def nettoyer(lettre: str, profil: Profile | None = None) -> str:
    """Retire ce que le document met en page lui-même.

    **On ne coupe qu'à la fin.** Une version antérieure supprimait tout à partir
    de la première formule de politesse rencontrée : « Dans l'attente de pouvoir
    en discuter… » ouvre couramment un paragraphe de milieu de lettre, et les
    trois quarts du texte disparaissaient. La lettre tronquée était ensuite
    rejetée comme trop courte, puis refusée — alors qu'elle était bonne.
    """
    # L'objet précède l'appel : les retirer dans le mauvais ordre laissait
    # « Madame, Monsieur, » en tête quand le modèle avait produit les deux.
    texte = lettre.strip()
    for _ in range(3):
        reduit = _APPEL.sub("", _OBJET.sub("", texte)).strip()
        if reduit == texte:
            break
        texte = reduit

    paragraphes = [p.strip() for p in texte.split("\n\n") if p.strip()]

    # Seule une formule reconnue fait retirer un paragraphe final. Une
    # heuristique « paragraphe court = signature » mangeait les fins de
    # lettre laconiques : « Troisieme paragraphe. » disparaissait.
    while len(paragraphes) > 1 and _est_formule_finale(paragraphes[-1]):
        paragraphes.pop()

    paragraphes = _retirer_signature(paragraphes, profil)

    # Formule collée en fin du dernier paragraphe : on coupe la ligne, pas tout.
    if paragraphes:
        lignes = list(paragraphes[-1].split("\n"))
        nom = normaliser(f"{profil.prenom} {profil.nom}") if profil else ""
        while len(lignes) > 1 and (_est_formule_finale(lignes[-1])
                                   or (nom and normaliser(lignes[-1]) == nom)):
            lignes.pop()
        paragraphes[-1] = "\n".join(lignes).strip()

    return "\n\n".join(p for p in paragraphes if p).strip()


# ------------------------------------------------------------------- le message


def _message(profil: Profile, offre: Offer) -> str:
    experiences = "\n".join(
        f"- {x.get('poste', '')} — {x.get('entreprise', '')} "
        f"({x.get('debut', '')} – {x.get('fin', '')}) : {x.get('description', '')}"
        for x in profil.experiences
    ) or "- (aucune expérience renseignée)"
    formations = "\n".join(
        f"- {f.get('diplome', '')} — {f.get('etablissement', '')} "
        f"({f.get('annee', '')}) {f.get('details', '')}".rstrip()
        for f in profil.formations
    ) or "- (aucune formation renseignée)"
    langues = ", ".join(
        f"{l.get('libelle', '')} ({l.get('niveau', '')})" for l in profil.langues
    ) or "non renseignées"
    competences = ", ".join(s.get("nom", "") for s in profil.skills) or "non renseignées"

    # Une disponibilité absente doit se voir : sans cette mention, le modèle en
    # invente une, et le dernier paragraphe promet une date que le candidat n'a
    # jamais donnée.
    disponibilite = profil.disponibilite or "(non renseignée — n'en annonce aucune)"

    return f"""{EXEMPLES_STYLE_COURT}

PROFIL
Nom : {profil.prenom} {profil.nom}
Situation actuelle : {profil.situation_actuelle or '(non renseignée)'}
Titre visé : {profil.titre_vise}
Ville : {profil.ville}
Disponibilité : {disponibilite}
Résumé : {profil.resume}
Compétences : {competences}
Langues : {langues}

Expériences :
{experiences}

Formations :
{formations}

OFFRE
Intitulé : {offre.titre}
Entreprise : {offre.entreprise or '(non précisée)'}
Lieu : {offre.lieu} {offre.pays}
Contrat : {offre.type_contrat or '(non précisé)'}
Description :
{offre.description_brute[:2500]}"""


# ------------------------------------------------------- les reproches au modèle


def _rappel_correction(suspects: list[str]) -> str:
    return (
        "Ta version précédente mentionnait ceci, qui ne figure NI dans le profil NI "
        f"dans l'offre : {', '.join(suspects)}. "
        "Réécris la lettre sans ces éléments. N'invente aucun nom propre."
    )


def _rappel_chiffres(nombres: list[str]) -> str:
    return (
        f"Ta version précédente avançait des chiffres absents du profil et de "
        f"l'offre : {', '.join(nombres)}. Un chiffre inventé est un mensonge sur "
        "mon parcours. N'emploie que les nombres qui figurent dans le PROFIL."
    )


def _rappel_copie(passages: list[str]) -> str:
    return (
        "Ta version précédente recopiait l'annonce mot pour mot : "
        + " / ".join(f"« {p} »" for p in passages)
        + ". Ces phrases décrivent le poste, pas mon parcours : les reprendre "
        "revient à m'attribuer des compétences que le profil ne mentionne pas. "
        "Dis avec mes propres mots ce que MON parcours apporte."
    )


def _rappel_contrat(mots_fautifs: list[str], offre: Offer) -> str:
    return (
        f"Ta version précédente parlait de « {', '.join(mots_fautifs)} » alors que "
        f"cette offre porte sur un contrat de type {offre.type_contrat}. "
        "N'emploie que le type de contrat de l'offre."
    )


def _rappel_disponibilite(annonces: list[str]) -> str:
    return (
        f"Ta version précédente annonçait une disponibilité (« {annonces[0]} ») "
        "alors que mon profil n'en indique aucune. Promettre une date que je n'ai "
        "pas donnée est une invention. Termine sans parler de disponibilité."
    )


def _rappel_cliches(formules: list[str]) -> str:
    return (
        "Ta version précédente contenait des formules creuses : "
        + " / ".join(f"« {f} »" for f in formules)
        + ". Chacune resterait vraie dans n'importe quelle lettre, pour "
        "n'importe quel poste. Réécris ces passages avec un fait précis tiré de "
        "mon parcours, ou supprime-les."
    )


def _rappel_ouverture(ouvertures: list[str]) -> str:
    return (
        f"Ta version précédente ouvrait par « {ouvertures[0]} ». Le recruteur en a "
        "déjà lu trois cents. Commence par un fait : ta situation actuelle et le "
        "poste visé, sans formule d'amorçage."
    )


def _rappel_rythme(fautes: list[str]) -> str:
    return (
        "Ta version précédente avait un rythme mécanique — " + " ; ".join(fautes)
        + ". Coupe une phrase longue en deux. Une phrase brève par paragraphe "
        "suffit à casser la régularité."
    )


def _rappel_voix(fautes: list[str]) -> str:
    return (
        "Ta version précédente était écrite du mauvais côté — on y lit : "
        f"{', '.join(fautes)}. Tu ES le candidat, tu postules. Parle de toi à la "
        "première personne (« je », « mon parcours », « mon expérience ») et "
        "réserve « vous » et « votre » à l'entreprise qui recrute. Tu ne "
        "proposes le poste à personne et tu ne recrutes personne."
    )


# Au-delà, le prompt gonfle plus vite que le modèle ne corrige : mesuré, mistral
# finit par rendre la structure du prompt au lieu d'une lettre. Les reproches
# bloquants passent devant, le style attendra l'essai suivant.
MAX_RAPPELS = 3


def _consignes(bloc: dict[str, list[str]], style: dict[str, list[str]],
               offre: Offer) -> list[str]:
    """Les reproches à joindre au prompt, les plus graves d'abord.

    Une lettre peut être à la fois inventive, mal orientée et convenue : n'en
    corriger qu'un ferait perdre un essai par faute. Mais tout lui reprocher
    d'un coup la fait décrocher — d'où le plafond.
    """
    rappels = []
    if bloc["inventions"]:
        rappels.append(_rappel_correction(bloc["inventions"]))
    if bloc["chiffres"]:
        rappels.append(_rappel_chiffres(bloc["chiffres"]))
    if bloc["voix"]:
        rappels.append(_rappel_voix(bloc["voix"]))
    if bloc["contrat"]:
        rappels.append(_rappel_contrat(bloc["contrat"], offre))
    if style["copies"]:
        rappels.append(_rappel_copie(style["copies"]))
    if style["disponibilite"]:
        rappels.append(_rappel_disponibilite(style["disponibilite"]))
    if style["cliches"]:
        rappels.append(_rappel_cliches(style["cliches"]))
    if style["ouverture"]:
        rappels.append(_rappel_ouverture(style["ouverture"]))
    if style["rythme"]:
        rappels.append(_rappel_rythme(style["rythme"]))
    return rappels[:MAX_RAPPELS]


# ------------------------------------------------------------------- relecture


def relire(lettre: str, generer, profil: Profile, offre: Offer) -> tuple[str, bool]:
    """Réécriture critique du brouillon. Renvoie (texte retenu, réécrit ?).

    L'idée est juste — un modèle repère mieux le générique qu'il ne l'évite —
    mais **mesurée sans effet sur mistral:7b** : il conserve la totalité des
    clichés qu'on lui demande de traquer, et n'a changé qu'un mot. D'où la
    détection en pur code, et ce réglage désactivé par défaut
    (`llm.relecture_lettre`), gardé pour un modèle plus capable.

    **La relecture ne doit jamais coûter une bonne lettre.** Si la réécriture
    échoue à un contrôle bloquant — le modèle « améliore » volontiers en
    inventant — on garde le brouillon, qui, lui, était accepté.
    """
    try:
        reecrite = nettoyer(generer(PROMPT_RELECTURE, lettre), profil)
    except Exception as e:  # noqa: BLE001 — une relecture ratée n'est pas fatale
        log.warning("Relecture impossible, brouillon conservé : %s", e)
        return lettre, False

    fautes = [f for liste in bloquantes(reecrite, profil, offre).values() for f in liste]
    nb_mots = len(reecrite.split())
    if fautes or not MOTS_MIN <= nb_mots <= MOTS_MAX:
        log.info("Relecture écartée (%s), brouillon conservé.",
                 ", ".join(fautes) or f"{nb_mots} mots")
        return lettre, False

    log.info("Relecture retenue (%d mots).", nb_mots)
    return reecrite, True


# ------------------------------------------------------------------- rédaction


def rediger(profil: Profile, offre: Offer, generer, tentatives: int = 3,
            relecture: bool = False) -> tuple[str, dict]:
    """Génère une lettre vérifiée.

    `generer(systeme, message) -> str` isole le fournisseur : Ollama ou
    Anthropic, la vérification reste la même.

    Renvoie (lettre, compte rendu). Lève si aucune tentative n'a produit de
    lettre **honnête** — mieux vaut pas de lettre qu'une lettre qui ment. Une
    lettre honnête mais convenue est livrée, avec ses défauts nommés dans le
    compte rendu.
    """
    message = _message(profil, offre)
    historique: list[dict] = []
    # Meilleure lettre honnête rencontrée, même si elle reste convenue.
    secours: tuple[str, int, dict] | None = None

    for essai in range(1, max(1, tentatives) + 1):
        systeme = PROMPT_SYSTEME
        if historique:
            precedent = historique[-1]
            rappels = _consignes(precedent["bloquantes"], precedent["style"], offre)
            if rappels:
                systeme += "\n\n" + "\n\n".join(rappels)

        # Le nettoyage passe AVANT les contrôles : une formule de politesse
        # retirée ne doit pas être comptée comme une invention.
        lettre = nettoyer(generer(systeme, message), profil)
        bloc = bloquantes(lettre, profil, offre)
        style = defauts_de_style(lettre, profil, offre)
        nb_mots = len(lettre.split())
        historique.append({"essai": essai, "bloquantes": bloc, "style": style,
                           "mots": nb_mots})

        fautes_bloquantes = [f for liste in bloc.values() for f in liste]
        fautes_de_style = [f for liste in style.values() for f in liste]

        if fautes_bloquantes or not MOTS_MIN <= nb_mots <= MOTS_MAX:
            log.warning("Lettre rejetée (essai %d) : %s", essai,
                        fautes_bloquantes or f"longueur {nb_mots} mots hors bornes")
            continue

        if not fautes_de_style:
            log.info("Lettre acceptée à l'essai %d (%d mots)", essai, nb_mots)
            retenue, reecrite = ((relire(lettre, generer, profil, offre))
                                 if relecture else (lettre, False))
            return retenue, {"essais": essai, "mots": len(retenue.split()),
                             "relue": reecrite, "style": {}, "cliches": [],
                             "historique": historique}

        # Honnête mais convenue : on retente pour le style, en la gardant sous
        # le coude. Un essai suivant peut très bien être pire.
        log.info("Lettre honnête mais convenue (essai %d) : %s", essai,
                 ", ".join(fautes_de_style))
        if secours is None:
            secours = (lettre, essai, style)

    # Aucune lettre irréprochable, mais une lettre honnête a été produite : elle
    # vaut mieux que pas de lettre du tout. L'utilisateur est prévenu de ce qui
    # reste — c'est à lui de retoucher, pas au programme de lui refuser le
    # document.
    if secours is not None:
        texte, essai, style = secours
        restants = [f for liste in style.values() for f in liste]
        log.warning("Lettre livrée avec des défauts de style : %s", ", ".join(restants))
        return texte, {"essais": essai, "mots": len(texte.split()), "relue": False,
                       "style": style, "cliches": style["cliches"],
                       "historique": historique}

    dernier = historique[-1]["bloquantes"]
    for cle, libelle in (
        ("inventions", "noms propres inventés"),
        ("chiffres", "chiffres inventés"),
        ("voix", "lettre écrite du mauvais côté, comme si le recruteur s'adressait "
                 "au candidat"),
        ("contrat", "le type de contrat ne correspond pas à l'offre"),
    ):
        if dernier[cle]:
            raison = f"{libelle} : {', '.join(dernier[cle])}"
            break
    else:
        raison = f"longueur inadaptée ({historique[-1]['mots']} mots)"

    raise ValueError(
        f"Après {len(historique)} tentatives, la lettre reste inutilisable — {raison}. "
        f"Essayez un modèle plus capable (llm.modele_local dans config.yaml) ou "
        f"rédigez-la à la main."
    )
