"""Le CV adapté à l'offre : résumé propre au poste, puces reformulées.

**C'est l'optimisation ATS honnête, et elle ne vaut que par ses contrôles.** Le
recruteur cherche dans son ATS les mots de SON annonce ; un CV qui dit
« Gestion des risques de crédit à l'export » ne sort pas sur « analyse du
risque de crédit ». Reprendre son vocabulaire quand il désigne la même chose
est légitime. Ajouter ce qu'il réclame et que le candidat n'a pas fait est une
fausse déclaration — plus grave sur un CV que dans une lettre.

Le modèle propose ; le code vérifie chaque puce, une à une :

- **aucun nombre** absent de la puce d'origine — pas même un nombre venu d'une
  autre expérience ;
- **aucun nom propre ni sigle** absent de la puce d'origine — « IFRS 9 » ou
  « Bloomberg » repris de l'annonce sont refusés ;
- **aucun mot porteur de sens** qui ne soit l'original, un synonyme métier
  (`scoring/synonymes.py`), un mot de la même famille (« évaluer » /
  « évaluation ») ou un mot générique (« gestion », « suivi ») ;
- **pas plus d'un tiers plus longue** : le CV doit tenir sur une page ;
- **aucune phrase recopiée** de l'annonce.

Une puce refusée n'annule rien : elle retombe sur l'originale, et le refus est
consigné dans `generation.json`. Un CV ciblé à moitié vaut mieux qu'un CV qui
ment à moitié.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from ..models import Offer, Profile
from ..scoring.score import presence
from ..scoring.texte import GENERIQUES, VIDES, mots
from .controles import _nombres, copies_de_l_offre, entites_suspectes, sources_texte
from .intitule import intitule_pour_cv

log = logging.getLogger("dreamjob.ciblage")

# Un tiers de plus au maximum, et toujours quelques mots de marge : une puce de
# six mots doit pouvoir gagner un complément.
ALLONGEMENT_MAX = 4 / 3
MARGE_MOTS = 4
MOTS_MAX_RESUME = 60
# Deux mots partageant ce préfixe sont de la même famille : « évalu(er) » /
# « évalu(ation) », « recouvr(er) » / « recouvr(ement) ». En deçà, « ge » de
# « gestion » rapprocherait n'importe quoi.
PREFIXE_FAMILLE = 5
DESCRIPTION_MAX = 3500

# Mots qui n'affirment rien : la grammaire d'une reformulation, et les tournures
# d'action qui ne revendiquent aucune compétence (« mise en place », « dans le
# cadre de »). Mesuré sur les puces réelles : sans eux, une réécriture honnête
# sur deux était refusée pour un « contre » ou un « mise ».
#
# Délibérément absents : les synonymes que la table métier ne connaît pas.
# « impayés » pour « non-paiement » est refusé — accepter un sens voisin, c'est
# ouvrir la porte au glissement. Une puce refusée garde son texte d'origine ;
# une puce acceptée à tort mentirait.
NEUTRES = {
    "contre", "entre", "sans", "sous", "vers", "afin", "lors", "ainsi", "dont",
    "mais", "puis", "chez", "selon", "via", "tout", "tous", "toute", "toutes",
    "chaque", "leurs", "ensemble", "mise", "place", "cadre", "niveau", "sein",
    "partir", "aupres", "pres", "egard", "travers", "quotidien", "quotidienne",
}

PROMPT_CIBLAGE = """Tu adaptes le CV d'un candidat à une offre d'emploi, en français. Tu ne mens jamais.

CE QUE TU FAIS
1. Pour chaque expérience, tu reformules chaque puce pour que le recruteur qui a
   écrit l'offre y retrouve SES mots — seulement quand ils désignent la même chose
   que la puce. « Gestion des risques de crédit à l'export » peut devenir
   « Analyse du risque de crédit export » si l'offre parle d'analyse du risque de
   crédit. Elle ne peut PAS devenir « Modélisation du risque de crédit (IFRS 9) » :
   ni la modélisation ni IFRS 9 ne figurent dans la puce.
2. Tu écris un résumé de deux phrases, 45 mots au plus, qui présente le candidat
   pour CE poste, à partir des seuls faits du PROFIL et des EXPÉRIENCES.

INTERDIT — la moindre entorse fait rejeter ta proposition, puce par puce :
- ajouter un fait, un chiffre, un outil, une norme, un logiciel, une entreprise,
  une compétence ou une responsabilité absents de la puce d'origine ;
- déplacer un chiffre d'une expérience à une autre ;
- prêter à la puce une exigence de l'offre qu'elle ne décrit pas : « contrôle »,
  « mesure », « identification », « pilotage » ne s'ajoutent pas à une puce qui
  parle de suivi ou d'évaluation ;
- recopier une phrase de l'offre ;
- allonger une puce de plus d'un tiers : le CV doit tenir sur une page.

FORME
- Pour chaque expérience, exactement autant de puces qu'à l'origine, dans le même
  ordre, sous le même numéro.
- Style de CV : phrase nominale ou infinitive, jamais « je ».
- Une puce qui ne gagne rien à être reformulée est recopiée telle quelle.
- Le résumé est impersonnel, sans « je ». Il accorde selon la ligne « Accord » du
  PROFIL, et n'accorde aucun adjectif si elle est absente.
- Aucun superlatif, aucune qualité autoproclamée (« rigoureux », « dynamique »)."""


class ExperienceCiblee(BaseModel):
    numero: int = Field(description="Le numéro [n] de l'expérience, tel que donné")
    puces: list[str] = Field(description="Les puces reformulées, même nombre et même ordre")


class PropositionCiblage(BaseModel):
    resume: str = Field(description="Deux phrases, 45 mots au plus")
    experiences: list[ExperienceCiblee]


@dataclass
class Ciblage:
    """Ce que le rendu du CV utilise, une fois les contrôles passés."""

    resume: str | None = None
    # Indice de l'expérience DANS LE PROFIL → ses puces, contrôlées.
    puces: dict[int, list[str]] = field(default_factory=dict)
    # Le compte rendu destiné à generation.json.
    journal: dict = field(default_factory=dict)


# ------------------------------------------------------------------ contrôles


# Un mot à majuscule initiale — nom propre ou sigle. Celui qui ouvre la puce ou
# une phrase est ignoré : sa majuscule est grammaticale.
_MAJUSCULE = re.compile(r"\b[A-ZÀ-Ý][\wÀ-ÿ&'-]*")
_FIN_DE_PHRASE = re.compile(r"[.!?:]\s*$")


def _meme_famille(jeton: str, source: set[str]) -> bool:
    if len(jeton) < PREFIXE_FAMILLE:
        return False
    return any(len(s) >= PREFIXE_FAMILLE and s[:PREFIXE_FAMILLE] == jeton[:PREFIXE_FAMILLE]
               for s in source)


def ajouts(originale: str, reecrite: str) -> list[str]:
    """Les mots porteurs de sens que la réécriture introduit.

    Un mot est admis s'il figure dans l'original, en est un synonyme métier ou
    une variante proche (`presence`, la fonction du scoring), appartient à la
    même famille, ou n'engage à rien (mot vide, mot générique).
    """
    source = set(mots(originale))
    nouveaux: list[str] = []
    for jeton in mots(reecrite):
        if (jeton in source or jeton in VIDES or jeton in GENERIQUES or jeton in NEUTRES
                or len(jeton) < 3):
            continue
        if jeton.isdigit():
            continue          # les nombres ont leur propre contrôle
        if _meme_famille(jeton, source):
            continue
        if presence(jeton, source, flou=True) > 0.0:
            continue
        if jeton not in nouveaux:
            nouveaux.append(jeton)
    return nouveaux


def _noms_propres_ajoutes(originale: str, reecrite: str) -> list[str]:
    """Majuscules hors début de puce, et sigles, absents de l'original."""
    source = set(mots(originale))
    ajoutes = []
    for m in _MAJUSCULE.finditer(reecrite):
        avant = reecrite[:m.start()]
        if not avant.strip() or _FIN_DE_PHRASE.search(avant):
            continue          # majuscule grammaticale
        jetons = mots(m.group())
        if jetons and not all(j in source for j in jetons) and m.group() not in ajoutes:
            ajoutes.append(m.group())
    return ajoutes


def verifier_puce(originale: str, reecrite: str, offre: Offer) -> list[str]:
    """Les raisons de refuser une puce réécrite. Vide : la puce est acceptée."""
    raisons: list[str] = []
    if not reecrite.strip():
        return ["puce vide"]

    nombres = sorted(_nombres(reecrite) - _nombres(originale))
    if nombres:
        raisons.append(f"nombre absent de l'original : {', '.join(nombres)}")

    noms = _noms_propres_ajoutes(originale, reecrite)
    if noms:
        raisons.append(f"nom propre ou sigle ajouté : {', '.join(noms)}")

    nouveaux = ajouts(originale, reecrite)
    if nouveaux:
        raisons.append(f"notion ajoutée : {', '.join(nouveaux)}")

    limite = max(len(originale.split()) * ALLONGEMENT_MAX, len(originale.split()) + MARGE_MOTS)
    if len(reecrite.split()) > limite:
        raisons.append(f"trop longue ({len(reecrite.split())} mots pour {len(originale.split())})")

    copies = copies_de_l_offre(reecrite, offre)
    if copies:
        raisons.append(f"recopie l'annonce : {copies[0]}")
    return raisons


def verifier_resume(resume: str, profil: Profile, offre: Offer) -> list[str]:
    """Le résumé ne peut citer que des faits du profil.

    Les chiffres se vérifient contre le PROFIL SEUL : un « 5 ans d'expérience »
    repris de l'annonce serait un mensonge, alors même qu'il figure dans l'offre.
    """
    raisons: list[str] = []
    if len(resume.split()) > MOTS_MAX_RESUME:
        raisons.append(f"trop long ({len(resume.split())} mots)")
    connus: set[str] = set()
    for morceau in sources_texte(profil, Offer(source="", source_id="")):
        connus |= _nombres(morceau)
    inventes = sorted(_nombres(resume) - connus)
    if inventes:
        raisons.append(f"nombre absent du profil : {', '.join(inventes)}")
    suspects = entites_suspectes(resume, profil, offre)
    if suspects:
        raisons.append(f"nom propre inconnu : {', '.join(suspects)}")
    if re.search(r"\b(je|j'|votre|vos)\b", resume, re.IGNORECASE):
        raisons.append("n'est pas impersonnel")
    return raisons


# ------------------------------------------------------------------- message


def _message(profil: Profile, offre: Offer, puces: dict[int, list[str]]) -> str:
    intitule = intitule_pour_cv(offre.titre, offre.lieu, profil.titre_vise, profil.accord)
    accord = {"masculin": "Accord : masculin", "feminin": "Accord : féminin"}.get(profil.accord, "")
    formations = "\n".join(
        f"- {f.get('diplome', '')}, {f.get('etablissement', '')} ({f.get('annee', '')})"
        for f in profil.formations)
    blocs = []
    for i, liste in puces.items():
        x = profil.experiences[i]
        entete = f"[{i}] {x.get('poste', '')} — {x.get('entreprise', '')} ({x.get('debut', '')} – {x.get('fin', '')})"
        blocs.append(entete + "\n" + "\n".join(f"  - {p}" for p in liste))

    return f"""OFFRE
Intitulé : {intitule}
Entreprise : {offre.entreprise or '(non précisée)'}
Description :
{(offre.description_brute or '')[:DESCRIPTION_MAX]}

PROFIL
{accord}
Situation : {profil.situation_actuelle or '(non renseignée)'}
Résumé actuel : {profil.resume or '(aucun)'}
Compétences : {', '.join(s.get('nom', '') for s in profil.skills)}
Formations :
{formations}

EXPÉRIENCES À REFORMULER
{chr(10).join(blocs)}"""


# --------------------------------------------------------------------- ciblage


def cibler(profil: Profile, offre: Offer, puces: dict[int, list[str]], appel) -> Ciblage:
    """Demande une adaptation au modèle, puis ne garde que ce qui passe les contrôles.

    `puces` : indice d'expérience dans le profil → puces d'origine, découpées
    exactement comme le rendu les découpera. `appel` expose
    `structure(systeme, message, format)`. Une erreur d'appel remonte : c'est à
    l'appelant de livrer le CV non ciblé.
    """
    proposition = appel.structure(PROMPT_CIBLAGE, _message(profil, offre, puces),
                                  PropositionCiblage)
    resultat = Ciblage()
    journal = {"resume": None, "puces_reecrites": 0, "puces_corrigees": 0,
               "puces_inchangees": 0, "puces_refusees": [], "experiences_ignorees": []}

    raisons = verifier_resume(proposition.resume.strip(), profil, offre)
    if raisons:
        journal["resume"] = {"refuse": proposition.resume, "raisons": raisons}
    else:
        resultat.resume = proposition.resume.strip()
        journal["resume"] = "retenu"

    # (expérience, position) → (originale, proposée, raisons du refus)
    refusees: dict[tuple[int, int], tuple[str, str, list[str]]] = {}
    proposees = {e.numero: e.puces for e in proposition.experiences}
    for i, originales in puces.items():
        nouvelles = proposees.get(i)
        if nouvelles is None or len(nouvelles) != len(originales):
            # Une expérience mal alignée n'est pas réparée : on ne devine pas
            # quelle puce correspond à quelle autre.
            journal["experiences_ignorees"].append(i)
            continue
        retenues = []
        for k, (originale, proposee) in enumerate(zip(originales, nouvelles)):
            proposee = _nettoyer_puce(proposee)
            if proposee == originale:
                journal["puces_inchangees"] += 1
            elif refus := verifier_puce(originale, proposee, offre):
                refusees[(i, k)] = (originale, proposee, refus)
            else:
                journal["puces_reecrites"] += 1
                retenues.append(proposee)
                continue
            retenues.append(originale)
        resultat.puces[i] = retenues

    if refusees:
        _corriger(profil, offre, refusees, appel, resultat, journal)

    journal["puces_refusees"] = [
        {"originale": o, "proposee": p, "raisons": r} for o, p, r in refusees.values()]
    resultat.journal = journal
    log.info("Ciblage : résumé %s, %d puces réécrites dont %d après correction, %d refusées",
             "retenu" if resultat.resume else "refusé",
             journal["puces_reecrites"], journal["puces_corrigees"], len(refusees))
    return resultat


def _nettoyer_puce(texte: str) -> str:
    return texte.strip().lstrip("-•– ").strip()


# --- Le second tour : nommer la faute ------------------------------------------
# Mesuré sur le premier dossier réel : Sonnet 5 a proposé cinq réécritures, les
# cinq ont été refusées. Il ajoutait les exigences de l'annonce (« contrôle »,
# « mesure », « identification ») — les refus étaient justes. Mais dans une même
# puce il mêlait un ajout abusif et une reformulation honnête (« limiter les
# risques » → « mitigation des risques »), et la puce entière partait. C'est la
# méthode qui a fait ses preuves sur la lettre : un modèle obéit quand on lui
# nomme la faute. Un seul tour, sur les seules puces refusées.

class PuceCorrigee(BaseModel):
    numero: int = Field(description="Le numéro [n] de l'expérience")
    position: int = Field(description="La position de la puce, telle que donnée")
    puce: str


class CorrectionCiblage(BaseModel):
    puces: list[PuceCorrigee]


def _message_correction(refusees: dict[tuple[int, int], tuple[str, str, list[str]]]) -> str:
    blocs = []
    for (i, k), (originale, proposee, raisons) in refusees.items():
        blocs.append(f"[{i}] position {k}\n  ORIGINE : {originale}\n  TA PROPOSITION : "
                     f"{proposee}\n  REFUSÉE CAR : {' ; '.join(raisons)}")
    return ("Ces reformulations ont été refusées par la vérification automatique. Pour "
            "chacune, propose une nouvelle version qui n'emploie AUCUN des mots refusés et "
            "n'ajoute rien à la puce d'origine. Garde ce qui était honnête dans ta "
            "proposition. Si tu ne peux rien améliorer sans ajouter, recopie l'origine "
            "telle quelle.\n\n" + "\n\n".join(blocs))


def _corriger(profil: Profile, offre: Offer, refusees: dict, appel,
              resultat: Ciblage, journal: dict) -> None:
    """Remplace dans `refusees` ce que la correction a réussi à rendre honnête.

    Une erreur d'appel ici n'efface pas le premier tour : ce qui avait été
    accepté reste acquis, et les puces refusées gardent leur texte d'origine.
    """
    try:
        correction = appel.structure(PROMPT_CIBLAGE, _message_correction(refusees),
                                     CorrectionCiblage)
    except Exception as e:  # noqa: BLE001
        log.warning("Correction du ciblage impossible : %s", e)
        journal["correction"] = str(e)
        return

    for puce in correction.puces:
        cle = (puce.numero, puce.position)
        if cle not in refusees or cle[0] not in resultat.puces:
            continue
        originale, _, _ = refusees[cle]
        nouvelle = _nettoyer_puce(puce.puce)
        if nouvelle == originale:
            continue
        refus = verifier_puce(originale, nouvelle, offre)
        if refus:
            refusees[cle] = (originale, nouvelle, refus)
            continue
        resultat.puces[cle[0]][cle[1]] = nouvelle
        journal["puces_reecrites"] += 1
        journal["puces_corrigees"] += 1
        del refusees[cle]
