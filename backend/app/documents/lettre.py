"""Lettre de motivation.

**Règle non négociable du projet : le LLM n'invente rien.** Aucune expérience,
aucun diplôme, aucune entreprise absente du profil ne doit apparaître.

La contrainte est posée dans le prompt système, mais un prompt n'est pas une
garantie — surtout avec un modèle local. Chaque lettre est donc **vérifiée**, et
rejetée puis régénérée si elle contient un nom propre ou une date inconnus.

**Quatre contrôles, pas un.** Les trois autres attrapent des lettres que le
premier laisse passer intactes, faute d'y trouver le moindre nom propre inventé.
Et ils ne pèsent pas tous le même poids :

| Contrôle | Ce qu'il attrape | Effet |
|---|---|---|
| invention | un nom propre ou une année inconnus | **bloquant** |
| voix | le recruteur s'adresse au candidat | **bloquant** |
| perroquet | l'annonce recopiée mot pour mot | **bloquant** |
| formules creuses | « relever les défis », « fort de mon expérience » | signalé |

**La distinction est délibérée.** Les trois premiers rendent la lettre
*malhonnête* : elle affirme quelque chose de faux sur le candidat. Le quatrième
la rend seulement *médiocre*. Refuser une lettre exacte parce qu'elle contient
« relever les défis » serait disproportionné : on la livre, et on nomme les
formules à retoucher. Mieux vaut pas de lettre qu'une lettre qui ment — mais une
lettre convenue vaut mieux que pas de lettre.

Ce quatrième contrôle a d'abord été tenté comme une **passe de relecture** : on
demandait au modèle de critiquer son propre brouillon. Mesuré sur mistral:7b, il
en conserve la totalité des clichés — il ne sait pas s'auto-critiquer. Il obéit
en revanche très bien quand on lui **nomme** la faute, comme pour la voix et le
perroquet. La passe de relecture reste disponible (`llm.relecture_lettre`) pour
un modèle plus capable, mais elle est désactivée par défaut.
"""

from __future__ import annotations

import logging
import re

from ..models import Offer, Profile
from ..scoring.texte import mots, normaliser

log = logging.getLogger("dreamjob.lettre")

MOTS_MAX = 320
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
ville ou date qui ne figure pas dans le PROFIL ou dans l'OFFRE ci-dessous. Si une
information te manque, tu écris la lettre sans elle. N'affirme jamais avoir
étudié ou travaillé quelque part sans que ce soit écrit.

TU NE RECOPIES PAS L'ANNONCE.
Reprendre une phrase de l'offre revient à s'attribuer une compétence que le
profil ne mentionne pas — et le recruteur reconnaît son propre texte. Dis avec
tes mots ce que TON parcours apporte à ce poste.

FORME
- Exactement trois paragraphes, 280 mots maximum au total. Pas quatre, pas cinq.
- Ne redonne pas ton nom : il figure déjà en en-tête de la lettre.
- Paragraphe 1 : le poste que je vise et ce qui, dans mon parcours, y répond
  directement.
- Paragraphe 2 : deux faits concrets tirés de mes expériences, chiffres compris
  quand ils sont donnés. Des faits reliés entre eux, pas une liste.
- Paragraphe 3 : ce que je cherche et ce que je peux apporter. N'annonce JAMAIS
  de date de disponibilité : elle ne figure pas dans le profil, l'inventer
  serait une faute.

TON
Sobre, direct, professionnel : quelqu'un qui écrit, pas un formulaire qu'on
remplit. Varie la longueur des phrases. Pas de superlatif, pas de « passionné
depuis toujours », pas de « dynamique et motivé », aucune formule creuse.
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
- La structure : trois paragraphes, et la même longueur d'ensemble.

Rends uniquement la lettre réécrite, sans commentaire ni explication."""

# Mots qui portent une majuscule sans être des noms propres à vérifier.
COURANTS = {
    "je", "j", "vous", "votre", "vos", "nous", "notre", "nos", "madame", "monsieur",
    "mesdames", "messieurs", "cordialement", "objet", "candidature", "lettre",
    "le", "la", "les", "un", "une", "ce", "cette", "mon", "ma", "mes", "au", "aux",
    "en", "dans", "pour", "avec", "sur", "par", "depuis", "apres", "avant", "enfin",
    "aujourd", "hui", "actuellement", "ainsi", "cependant", "toutefois",
    "titulaire", "diplome", "master", "licence", "bachelor", "bac", "mba", "bts", "dut",
    "janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout",
    "septembre", "octobre", "novembre", "decembre",
    "cdi", "cdd", "stage", "alternance", "interim", "vie", "france", "europe",
    "anglais", "francais", "allemand", "espagnol", "italien",
}

_DEBUT_PHRASE = re.compile(r"(?:^|[.!?:;]\s+|\n\s*)$")
_MOT_CAPITALISE = re.compile(r"\b[A-ZÀ-Þ][\wÀ-ÿ'’.-]{2,}")
_ANNEE = re.compile(r"\b(?:19|20)\d{2}\b")

# Formules d'appel et de politesse : le modèle en ajoute malgré la consigne, et
# le document les met en page lui-même. On les retire plutôt que de rejeter.
_APPEL = re.compile(
    r"^\s*(?:cher|chère|chere|madame|monsieur|mesdames|messieurs)[^\n]{0,60}[,:]\s*",
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


def nettoyer(lettre: str) -> str:
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

    # Formule collée en fin du dernier paragraphe : on coupe la ligne, pas tout.
    if paragraphes:
        lignes = [l for l in paragraphes[-1].split("\n")]
        while len(lignes) > 1 and _est_formule_finale(lignes[-1]):
            lignes.pop()
        paragraphes[-1] = "\n".join(lignes).strip()

    return "\n\n".join(p for p in paragraphes if p).strip()


def _sources_texte(profil: Profile, offre: Offer) -> list[str]:
    """Tout ce que le candidat et l'offre mentionnent réellement."""
    morceaux: list[str] = [
        profil.prenom, profil.nom, profil.ville, profil.pays, profil.titre_vise,
        profil.resume, offre.titre, offre.entreprise, offre.lieu, offre.pays,
        offre.description_brute,
    ]
    morceaux += profil.secteurs
    morceaux += [s.get("nom", "") for s in profil.skills]
    morceaux += [lg.get("libelle", "") for lg in profil.langues]
    for experience in profil.experiences:
        morceaux += [experience.get("entreprise", ""), experience.get("poste", ""),
                     experience.get("lieu", ""), experience.get("description", ""),
                     experience.get("debut", ""), experience.get("fin", "")]
        morceaux += experience.get("tags", [])
    for formation in profil.formations:
        morceaux += [formation.get("etablissement", ""), formation.get("diplome", ""),
                     formation.get("lieu", ""), formation.get("details", ""),
                     formation.get("annee", "")]
    return [m for m in morceaux if m]


def _vocabulaire_autorise(profil: Profile, offre: Offer) -> set[str]:
    autorise = set(COURANTS)
    for morceau in _sources_texte(profil, offre):
        autorise.update(normaliser(morceau).split())
    return autorise


def entites_suspectes(lettre: str, profil: Profile, offre: Offer) -> list[str]:
    """Noms propres et années de la lettre absents du profil et de l'offre.

    Les mots en début de phrase sont ignorés : leur majuscule y est
    grammaticale, pas significative.
    """
    autorise = _vocabulaire_autorise(profil, offre)
    suspects: list[str] = []

    for correspondance in _MOT_CAPITALISE.finditer(lettre):
        if _DEBUT_PHRASE.search(lettre[:correspondance.start()]):
            continue
        mot = correspondance.group()
        # `mots()` retire la ponctuation de bord : « Exemple. » doit être reconnu
        # comme « Exemple », sinon toute fin de phrase devient suspecte.
        jetons = mots(mot) or [normaliser(mot)]
        if all(j in autorise for j in jetons):
            continue
        if mot not in suspects:
            suspects.append(mot)

    # Les dates aussi s'inventent : un modèle annonce volontiers une
    # disponibilité que le candidat n'a jamais donnée.
    annees_connues = {a.group() for morceau in _sources_texte(profil, offre)
                      for a in _ANNEE.finditer(morceau)}
    for annee in _ANNEE.finditer(lettre):
        if annee.group() not in annees_connues and annee.group() not in suspects:
            suspects.append(annee.group())

    return suspects

# --- La voix de la lettre ----------------------------------------------------
# Un modèle local se met volontiers du mauvais côté : il devient le recruteur et
# propose le poste au candidat (« Votre profil correspond… », « je recherche un
# candidat expérimenté »). La lettre reste pourtant *vraie* — tous les noms
# propres viennent bien du profil — donc le contrôle anti-invention la laisse
# passer sans un mot. Il faut un contrôle distinct.

_MARQUES_PREMIERE_PERSONNE = {"je", "j", "mon", "ma", "mes", "moi"}

# Tournures qui ne peuvent désigner que le candidat : les rencontrer au « vous »
# signifie que la lettre lui est adressée au lieu d'être écrite par lui.
# « votre entreprise », « votre équipe », « vos besoins » sont parfaitement
# légitimes et n'ont rien à faire dans cette liste.
_TOURNURES_INVERSEES = (
    "votre profil", "votre candidature", "votre cv", "votre curriculum",
    "votre parcours", "votre carriere", "votre formation", "votre diplome",
    "vous avez demontre", "vous avez acquis", "vous avez occupe",
    "vous avez travaille", "vous disposez d",
    "je recherche un candidat", "nous recherchons un candidat",
    "je vous propose ce poste", "votre capacite a",
)


def voix_incorrecte(lettre: str) -> list[str]:
    """Signes que la lettre n'est pas écrite par le candidat lui-même."""
    nu = normaliser(lettre)
    fautes = [t for t in _TOURNURES_INVERSEES if t in nu]
    if not _MARQUES_PREMIERE_PERSONNE & set(nu.split()):
        fautes.append("aucune marque de première personne (« je », « mon »)")
    return fautes


# --- Le perroquet ------------------------------------------------------------
# Faute de matière, un modèle recopie les exigences de l'annonce et les présente
# comme le parcours du candidat. Rien n'est « inventé » au sens du premier
# contrôle — les mots viennent bien de l'offre — mais le candidat s'attribue des
# compétences qu'il n'a pas, et un recruteur reconnaît sa propre annonce au
# premier coup d'œil.

# Le seuil est un compromis, mesuré sur des lettres réelles :
#
#   « au sein d'un Middle office Assurance H/F en CDI »            10 jetons
#   « à l'aise à l'oral, notamment au téléphone, que par écrit »   11 jetons
#   « la conformité et la complétude des actes de gestion… »       14 jetons
#   « polyvalent sur tous les actes concernant l'assurance vie… »  15 jetons
#
# Les deux premières sont légitimes — on doit pouvoir nommer le poste auquel on
# postule — les deux dernières sont de vraies recopies. À huit jetons, tout
# était refusé et mistral n'arrivait jamais au bout. Douze sépare correctement.
# Le prix : une reprise courte passe encore, mais elle porte rarement une
# compétence revendiquée.
LONGUEUR_COPIE = 12


def _suites(jetons: list[str], longueur: int) -> set[tuple[str, ...]]:
    return {tuple(jetons[i:i + longueur]) for i in range(len(jetons) - longueur + 1)}


def copies_de_l_offre(lettre: str, offre: Offer) -> list[str]:
    """Passages recopiés mot pour mot depuis l'annonce."""
    de_la_lettre = mots(lettre, garder_vides=True)
    de_l_offre = mots(offre.description_brute or "", garder_vides=True)
    if len(de_la_lettre) < LONGUEUR_COPIE or len(de_l_offre) < LONGUEUR_COPIE:
        return []
    communes = (_suites(de_la_lettre, LONGUEUR_COPIE)
                & _suites(de_l_offre, LONGUEUR_COPIE))
    # Trois exemples suffisent à faire comprendre le reproche au modèle.
    return [" ".join(suite) for suite in sorted(communes)][:3]


# --- Les formules creuses ----------------------------------------------------
# On a d'abord demandé au modèle de relire son propre brouillon et d'en retirer
# les clichés. Mesuré : mistral:7b en conserve la totalité — il ne sait pas
# s'auto-critiquer. Il obéit en revanche très bien quand on lui NOMME la faute,
# comme pour la voix et le perroquet. D'où cette liste, en pur code.
#
# Elle reste volontairement courte et sans ambiguïté : chaque entrée est une
# phrase qui resterait vraie dans n'importe quelle lettre, pour n'importe quel
# poste. Une liste trop large ferait refuser des lettres correctes.
_CLICHES = (
    "fort de mon experience", "fort de mes experiences",
    "je suis convaincu", "je suis persuade",
    "n hesitez pas a", "je reste a votre entiere disposition",
    "dynamique et motive", "rigoureux et motive",
    "relever les defis", "relever de nouveaux defis", "relever ce defi",
    "apporter mes talents", "ma devotion",
    "resultats exceptionnels", "resultats remarquables",
    "j attends avec impatience", "j attends donc avec impatience",
    "depuis toujours passionne", "passionne depuis toujours",
    "mener a bien les taches", "avec succes les taches",
    "veritable atout", "atout majeur pour votre entreprise",
    "contribuer a la reussite de votre entreprise",
)


def cliches(lettre: str) -> list[str]:
    """Formules creuses repérées dans la lettre."""
    nu = normaliser(lettre)
    return [c for c in _CLICHES if c in nu]


def _message(profil: Profile, offre: Offer) -> str:
    experiences = "\n".join(
        f"- {x.get('poste', '')} — {x.get('entreprise', '')} "
        f"({x.get('debut', '')} – {x.get('fin', '')}) : {x.get('description', '')}"
        for x in profil.experiences
    ) or "- (aucune expérience renseignée)"
    formations = "\n".join(
        f"- {f.get('diplome', '')} — {f.get('etablissement', '')} ({f.get('annee', '')})"
        for f in profil.formations
    ) or "- (aucune formation renseignée)"
    langues = ", ".join(
        f"{l.get('libelle', '')} ({l.get('niveau', '')})" for l in profil.langues
    ) or "non renseignées"
    competences = ", ".join(s.get("nom", "") for s in profil.skills) or "non renseignées"

    return f"""PROFIL
Nom : {profil.prenom} {profil.nom}
Titre : {profil.titre_vise}
Ville : {profil.ville}
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
Contrat : {offre.type_contrat}
Description :
{offre.description_brute[:2500]}"""


def _rappel_correction(suspects: list[str]) -> str:
    return (
        "Ta version précédente mentionnait ceci, qui ne figure NI dans le profil NI "
        f"dans l'offre : {', '.join(suspects)}. "
        "Réécris la lettre sans ces éléments. N'invente aucun nom propre."
    )


def _rappel_copie(passages: list[str]) -> str:
    return (
        "Ta version précédente recopiait l'annonce mot pour mot : "
        + " / ".join(f"« {p} »" for p in passages)
        + ". Ces phrases décrivent le poste, pas mon parcours : les reprendre "
        "revient à m'attribuer des compétences que le profil ne mentionne pas. "
        "Dis avec mes propres mots ce que MON parcours apporte."
    )


def _rappel_cliches(formules: list[str]) -> str:
    return (
        "Ta version précédente contenait des formules creuses : "
        + " / ".join(f"« {f} »" for f in formules)
        + ". Chacune resterait vraie dans n'importe quelle lettre, pour "
        "n'importe quel poste. Réécris ces passages avec un fait précis tiré de "
        "mon parcours, ou supprime-les."
    )


def _rappel_voix(fautes: list[str]) -> str:
    return (
        "Ta version précédente était écrite du mauvais côté — on y lit : "
        f"{', '.join(fautes)}. Tu ES le candidat, tu postules. Parle de toi à la "
        "première personne (« je », « mon parcours », « mon expérience ») et "
        "réserve « vous » et « votre » à l'entreprise qui recrute. Tu ne "
        "proposes le poste à personne et tu ne recrutes personne."
    )


def _defauts(lettre: str, profil: Profile, offre: Offer) -> list[str]:
    """Les trois contrôles réunis, plus la longueur."""
    nb_mots = len(lettre.split())
    defauts = (entites_suspectes(lettre, profil, offre)
               + voix_incorrecte(lettre)
               + copies_de_l_offre(lettre, offre)
               + cliches(lettre))
    if not MOTS_MIN <= nb_mots <= MOTS_MAX:
        defauts.append(f"longueur {nb_mots} mots hors bornes")
    return defauts


def relire(lettre: str, generer, profil: Profile, offre: Offer) -> tuple[str, bool]:
    """Réécriture critique du brouillon. Renvoie (texte retenu, réécrit ?).

    Un modèle repère bien mieux le générique qu'il ne l'évite du premier coup :
    c'est cette passe qui retire les formules toutes faites et casse le rythme
    mécanique. Elle coûte un appel local de plus, donc rien.

    **La relecture ne doit jamais coûter une bonne lettre.** Si la réécriture
    échoue à l'un des trois contrôles — le modèle « améliore » volontiers en
    inventant — on garde le brouillon, qui, lui, était accepté.
    """
    try:
        reecrite = nettoyer(generer(PROMPT_RELECTURE, lettre))
    except Exception as e:  # noqa: BLE001 — une relecture ratée n'est pas fatale
        log.warning("Relecture impossible, brouillon conservé : %s", e)
        return lettre, False

    defauts = _defauts(reecrite, profil, offre)
    if defauts:
        log.info("Relecture écartée (%s), brouillon conservé.", ", ".join(defauts))
        return lettre, False

    log.info("Relecture retenue (%d mots).", len(reecrite.split()))
    return reecrite, True


def rediger(profil: Profile, offre: Offer, generer, tentatives: int = 3,
            relecture: bool = False) -> tuple[str, dict]:
    """Génère une lettre vérifiée.

    `generer(systeme, message) -> str` isole le fournisseur : Ollama ou Anthropic,
    la vérification reste la même.

    Renvoie (lettre, compte rendu). Lève si aucune tentative ne passe le contrôle
    — mieux vaut pas de lettre qu'une lettre qui ment sur le parcours.
    """
    message = _message(profil, offre)
    historique: list[dict] = []
    derniere = ""
    # Meilleure lettre honnête rencontrée, même si elle reste convenue.
    secours: tuple[str, int, list[str]] | None = None

    for essai in range(1, max(1, tentatives) + 1):
        systeme = PROMPT_SYSTEME
        if historique:
            # Les deux reproches se cumulent : une lettre peut être à la fois
            # inventive et écrite du mauvais côté, et n'en corriger qu'un
            # ferait perdre un essai sur deux.
            precedent = historique[-1]
            if precedent["suspects"]:
                systeme += "\n\n" + _rappel_correction(precedent["suspects"])
            if precedent["voix"]:
                systeme += "\n\n" + _rappel_voix(precedent["voix"])

        # Le nettoyage passe AVANT le contrôle : une formule de politesse
        # retirée ne doit pas être comptée comme une invention.
        derniere = nettoyer(generer(systeme, message))
        suspects = entites_suspectes(derniere, profil, offre)
        voix = voix_incorrecte(derniere)
        copies = copies_de_l_offre(derniere, offre)
        formules = cliches(derniere)
        nb_mots = len(derniere.split())
        historique.append({"essai": essai, "suspects": suspects, "voix": voix,
                           "copies": copies, "cliches": formules, "mots": nb_mots})

        # Deux familles de fautes, deux traitements. Invention, voix inversée et
        # recopie de l'annonce rendent la lettre MALHONNÊTE : elles bloquent.
        # Une formule creuse la rend seulement médiocre — refuser toute une
        # lettre exacte pour « relever les défis » serait disproportionné.
        bloquantes = suspects + voix + copies
        if not bloquantes and MOTS_MIN <= nb_mots <= MOTS_MAX:
            if not formules:
                log.info("Lettre acceptée à l'essai %d (%d mots)", essai, nb_mots)
                retenue, reecrite = ((relire(derniere, generer, profil, offre))
                                     if relecture else (derniere, False))
                return retenue, {"essais": essai, "mots": len(retenue.split()),
                                 "relue": reecrite, "cliches": [],
                                 "historique": historique}
            # Honnête mais convenue : on retente pour le style, en la gardant
            # sous le coude. Un essai suivant peut très bien être pire.
            if secours is None:
                secours = (derniere, essai, formules)

        log.warning("Lettre rejetée (essai %d) : %s", essai,
                    suspects + voix + copies + formules
                    or f"longueur {nb_mots} mots hors bornes")

    # Aucune lettre irréprochable, mais une lettre honnête a été produite :
    # elle vaut mieux que pas de lettre du tout. L'utilisateur est prévenu des
    # formules qui restent — c'est à lui de les retoucher, pas au programme de
    # lui refuser le document.
    if secours is not None:
        texte, essai, formules = secours
        log.warning("Lettre livrée avec des formules convenues : %s",
                    ", ".join(formules))
        return texte, {"essais": essai, "mots": len(texte.split()),
                       "relue": False, "cliches": formules,
                       "historique": historique}

    dernier = historique[-1]
    if dernier["suspects"]:
        raison = f"noms propres inventés : {', '.join(dernier['suspects'])}"
    elif dernier["voix"]:
        raison = ("lettre écrite du mauvais côté, comme si le recruteur "
                  f"s'adressait au candidat : {', '.join(dernier['voix'])}")
    elif dernier["copies"]:
        raison = ("l'annonce est recopiée mot pour mot : "
                  + " / ".join(dernier["copies"]))
    elif dernier["cliches"]:
        raison = "formules creuses : " + " / ".join(dernier["cliches"])
    else:
        raison = f"longueur inadaptée ({dernier['mots']} mots)"
    raise ValueError(
        f"Après {len(historique)} tentatives, la lettre reste inutilisable — {raison}. "
        f"Essayez un modèle plus capable (llm.modele_local dans config.yaml) ou "
        f"rédigez-la à la main."
    )
