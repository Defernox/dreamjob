"""Lettre de motivation.

**Règle non négociable du projet : le LLM n'invente rien.** Aucune expérience,
aucun diplôme, aucune entreprise absente du profil ne doit apparaître.

La contrainte est posée dans le prompt système, mais un prompt n'est pas une
garantie — surtout avec un modèle local. Chaque lettre est donc **vérifiée**, et
rejetée puis régénérée si elle contient un nom propre ou une date inconnus.
"""

from __future__ import annotations

import logging
import re

from ..models import Offer, Profile
from ..scoring.texte import mots, normaliser

log = logging.getLogger("dreamjob.lettre")

MOTS_MAX = 320
MOTS_MIN = 90

PROMPT_SYSTEME = """Tu rédiges une lettre de motivation en français, pour un candidat réel.

INTERDIT ABSOLU — TU N'INVENTES RIEN.
Tu ne mentionnes aucune entreprise, école, diplôme, certification, technologie,
ville ou date qui ne figure pas dans le PROFIL ou dans l'OFFRE ci-dessous. Si une
information te manque, tu écris la lettre sans elle. Ne suppose jamais qu'un
candidat a étudié quelque part ou travaillé quelque part sans que ce soit écrit.

FORME
- Trois paragraphes, 300 mots maximum au total.
- Paragraphe 1 : le poste visé et ce qui, dans le parcours, y répond directement.
- Paragraphe 2 : deux faits concrets tirés des expériences, chiffres compris
  quand ils sont donnés.
- Paragraphe 3 : ce que le candidat cherche. N'annonce JAMAIS de date de
  disponibilité : elle ne figure pas dans le profil, l'inventer serait une faute.

TON
Sobre et factuel. Pas de superlatif, pas de « passionné depuis toujours », pas de
« dynamique et motivé ». Aucune formule creuse. Le vouvoiement, et rien d'autre.

Rends uniquement le corps de la lettre : ni en-tête, ni adresse, ni date, ni
objet, ni formule d'appel, ni formule de politesse finale, ni signature. Ces
éléments sont ajoutés automatiquement après toi."""

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
_POLITESSE = re.compile(
    r"\n\s*(?:cordialement|sincèrement|sincerement|respectueusement|veuillez agréer|"
    r"je vous prie d.agréer|dans l.attente)[\s\S]*$",
    re.IGNORECASE,
)


def nettoyer(lettre: str) -> str:
    """Retire ce que le document met en page lui-même."""
    texte = _APPEL.sub("", lettre.strip())
    return _POLITESSE.sub("", texte).strip()


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


def rediger(profil: Profile, offre: Offer, generer, tentatives: int = 3) -> tuple[str, dict]:
    """Génère une lettre vérifiée.

    `generer(systeme, message) -> str` isole le fournisseur : Ollama ou Anthropic,
    la vérification reste la même.

    Renvoie (lettre, compte rendu). Lève si aucune tentative ne passe le contrôle
    — mieux vaut pas de lettre qu'une lettre qui ment sur le parcours.
    """
    message = _message(profil, offre)
    historique: list[dict] = []
    derniere = ""

    for essai in range(1, max(1, tentatives) + 1):
        systeme = PROMPT_SYSTEME
        if historique and historique[-1]["suspects"]:
            systeme += "\n\n" + _rappel_correction(historique[-1]["suspects"])

        # Le nettoyage passe AVANT le contrôle : une formule de politesse
        # retirée ne doit pas être comptée comme une invention.
        derniere = nettoyer(generer(systeme, message))
        suspects = entites_suspectes(derniere, profil, offre)
        nb_mots = len(derniere.split())
        historique.append({"essai": essai, "suspects": suspects, "mots": nb_mots})

        if not suspects and MOTS_MIN <= nb_mots <= MOTS_MAX:
            log.info("Lettre acceptée à l'essai %d (%d mots)", essai, nb_mots)
            return derniere, {"essais": essai, "mots": nb_mots, "historique": historique}

        log.warning("Lettre rejetée (essai %d) : %s", essai,
                    suspects or f"longueur {nb_mots} mots hors bornes")

    dernier = historique[-1]
    raison = (f"noms propres inventés : {', '.join(dernier['suspects'])}"
              if dernier["suspects"] else f"longueur inadaptée ({dernier['mots']} mots)")
    raise ValueError(
        f"Après {len(historique)} tentatives, la lettre reste inutilisable — {raison}. "
        f"Essayez un modèle plus capable (config.yaml → llm.modele_local) ou "
        f"rédigez-la à la main."
    )
