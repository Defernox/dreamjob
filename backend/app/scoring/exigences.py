"""Ce qu'une annonce exige du candidat — lu dans son texte, en pur code.

Quatre questions, auxquelles l'annonce répond souvent sans les poser :

- **Quel niveau de poste ?** L'intitulé le dit presque toujours : « Directeur
  administratif et financier » n'est pas accessible avec trois ans d'expérience,
  quelle que soit la proximité du métier. Le premier classement plaçait pourtant
  un DAF dans le top 20.
- **Combien d'années ?** Quand elles sont chiffrées.
- **Quel diplôme ?** Un poste à Bac+2 pour un Master 2 n'est pas une impasse,
  mais c'est rarement le bon poste.
- **Une certification ou un statut obligatoires ?** Expert-comptable, DSCG,
  CFA… ou fonctionnaire titulaire : ceux-là ferment la porte.
"""

from __future__ import annotations

import re

from .texte import normaliser

# --- Niveau du poste, d'après l'intitulé ---------------------------------------

NIVEAUX = ("stage", "junior", "intermediaire", "confirme", "encadrement", "direction")
RANG = {niveau: rang for rang, niveau in enumerate(NIVEAUX)}

_DIRECTION = re.compile(
    r"\b(directeur|directrice|director|head|chief|cfo|coo|ceo|daf|raf groupe|"
    r"managing director|partner|associe gerant)\b")
# Les banques gonflent les titres : un « Vice President » y encadre, sans diriger.
_ENCADREMENT = re.compile(
    r"\b(responsable|manager|managers|lead|chef|superviseur|supervisor|principal|"
    r"principale|team leader|encadrant|vice president|vp)\b")
_CONFIRME = re.compile(r"\b(senior|sr|confirme|confirmee|experimente|experimentee|expert)\b")
_STAGE = re.compile(
    r"\b(stage|stagiaire|intern|internship|alternance|alternant|alternante|apprenti|"
    r"apprentie|apprentissage|estagio|estagiario|praktikum|tirocinio)\b")
_JUNIOR = re.compile(
    r"\b(junior|jr|assistant|assistante|debutant|debutante|jeune diplome|"
    r"jeune diplomee|graduate|entry level|trainee|v\.?i\.?e|volontariat)\b")
_ADJOINT = re.compile(r"\b(adjoint|adjointe|deputy|assistant manager)\b")
# Les grades bancaires anglo-saxons trompent : un « Assistant Vice President »
# a quelques années d'expérience, un « Associate Director » encadre sans diriger.
_AVP = re.compile(r"\b(assistant vice president|avp)\b")
_ASSOCIATE_DIRECTOR = re.compile(r"\bassociate director\b")


def niveau_intitule(titre: str | None) -> str:
    """Le niveau que l'intitulé annonce. Sans marqueur : intermédiaire — le cas
    d'un « Analyste », d'un « Chargé » ou d'un « Gestionnaire »."""
    t = normaliser(titre)
    adjoint = bool(_ADJOINT.search(t))
    if _AVP.search(t):
        return "confirme"
    if _ASSOCIATE_DIRECTOR.search(t):
        return "encadrement"
    if _DIRECTION.search(t):
        # « Directeur adjoint » encadre, mais ne dirige pas.
        return "encadrement" if adjoint else "direction"
    if _STAGE.search(t):
        return "stage"
    if _ENCADREMENT.search(t):
        # « Adjoint au responsable », « Assistant Manager » : un cran en dessous.
        return "confirme" if adjoint else "encadrement"
    if _CONFIRME.search(t):
        return "confirme"
    if _JUNIOR.search(t):
        return "junior"
    return "intermediaire"


# --- Années d'expérience chiffrées ------------------------------------------------

# « 3 à 5 ans d'expérience » : c'est le 3 qui ouvre la porte.
_INTERVALLE = re.compile(
    r"(\d{1,2})\s*(?:a|à|-|–|to|/)\s*(\d{1,2})\s*(?:ans|annees|years|yrs)\b")
_EXPERIENCE = re.compile(r"\b(?:experience|exp)\b")
_SEUIL = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:ans|an|annees|annee|years|year|yrs)\s*\+?\s*"
    r"(?:minimum|mini|au moins|or more)?\s*(?:d.?\s*|of\s+)?(?:\w+\s+){0,3}?"
    r"(?:experience|exp)\b")
# « une expérience de 5 ans minimum » : le nombre après le mot.
_APRES = re.compile(
    r"experience\s+(?:\w+\s+){0,4}?(?:de\s+|d.?au moins\s+|of\s+)?(\d{1,2})\s*\+?\s*"
    r"(?:ans|an|annees|years|yrs)\b")
# Au-delà, c'est l'ancienneté de l'entreprise (« fort de 30 ans d'expérience »),
# pas une exigence faite au candidat.
ANNEES_PLAUSIBLES = 15


def annees_exigees(texte: str | None) -> int | None:
    """Le plancher d'années le plus exigeant que l'annonce chiffre, ou None."""
    t = normaliser(texte)
    if not t:
        return None
    planchers = []
    fourchettes = []
    for m in _INTERVALLE.finditer(t):
        # Une fourchette ne compte que si l'expérience est nommée tout près,
        # avant (« expérience de 3 à 5 ans ») ou après (« 3 à 5 ans d'expérience »).
        voisinage = t[max(0, m.start() - 40): m.end() + 40]
        if _EXPERIENCE.search(voisinage):
            planchers.append(min(int(m.group(1)), int(m.group(2))))
        fourchettes.append(m.span())
    for m in [*_SEUIL.finditer(t), *_APRES.finditer(t)]:
        # Le « 5 ans » de « 3 à 5 ans » n'est pas un second plancher.
        if any(debut <= m.start(1) < fin for debut, fin in fourchettes):
            continue
        planchers.append(int(m.group(1)))
    planchers = [a for a in planchers if 0 < a <= ANNEES_PLAUSIBLES]
    return max(planchers) if planchers else None


# --- Diplômes -------------------------------------------------------------------------

_ETUDES: list[tuple[re.Pattern, int]] = [
    (re.compile(r"\bbac\s*\+\s*(\d)\b"), -1),                  # la valeur est dans le motif
    (re.compile(r"\b(bts|dut|deug)\b"), 2),
    (re.compile(r"\b(licence|bachelor|bachelors|bsc)\b"), 3),
    # Pas « maîtrise » : le diplôme n'existe plus, et le mot est partout dans les
    # annonces (« maîtrise d'Excel ») — il transformait un poste Bac+2 en Bac+4.
    (re.compile(r"\b(master 1|m1)\b"), 4),
    (re.compile(r"\b(master|masters|msc|mba|grande ecole|ecole de commerce|"
                r"business school|ecole d.?ingenieur|diplome d.?ingenieur|"
                r"master.s degree)\b"), 5),
    (re.compile(r"\b(doctorat|phd|doctorate)\b"), 8),
]


def niveaux_etudes(texte: str | None) -> list[int]:
    """Les niveaux d'études (en années après le bac) que le texte mentionne."""
    t = normaliser(texte)
    trouves = []
    for motif, niveau in _ETUDES:
        for m in motif.finditer(t):
            if niveau == -1:
                valeur = int(m.group(1))
                if 1 <= valeur <= 8:
                    trouves.append(valeur)
            else:
                trouves.append(niveau)
    return trouves


# --- Certifications et statuts qui ferment la porte ----------------------------------------

CERTIFICATIONS = {
    "expert-comptable": r"expert.?comptable|\bdec\b|diplome d.?expertise comptable",
    "DSCG": r"\bdscg\b",
    "DCG": r"\bdcg\b",
    "CFA": r"\bcfa\b",
    "ACCA": r"\bacca\b",
    "CPA": r"\bcpa\b",
    "FRM": r"\bfrm\b",
    "actuaire": r"\bactuaire\b|\bactuary\b",
}
_EXIGENCE = re.compile(
    r"exige|requis|obligatoire|indispensable|imperati|necessaire|required|mandatory|"
    r"must|titulaire|diplome d|detenteur|holder")
_STATUT_PUBLIC = re.compile(
    r"titulaire de la fonction publique|fonctionnaire|voie statutaire|"
    r"cadre d.?emplois|laureat du concours|par voie de mutation|detachement")
_CONTRACTUEL = re.compile(r"contractuel|contractuelle|a defaut|ou contrat")


def certifications_exigees(texte: str | None) -> list[str]:
    """Les certifications que l'annonce EXIGE — citées près d'un « requis »,
    « obligatoire », « titulaire »… Simplement citées (« le CFA est un plus »),
    elles ne comptent pas."""
    t = normaliser(texte)
    exigees = []
    for nom, motif in CERTIFICATIONS.items():
        for m in re.finditer(motif, t):
            voisinage = t[max(0, m.start() - 80): m.end() + 80]
            if _EXIGENCE.search(voisinage) and "un plus" not in voisinage \
                    and "apprecie" not in voisinage and "idealement" not in voisinage:
                exigees.append(nom)
                break
    return exigees


def statut_public_exige(texte: str | None) -> bool:
    """Le poste est-il réservé aux fonctionnaires ? Pas si l'annonce ouvre aussi
    aux contractuels, ce que font la plupart des collectivités."""
    t = normaliser(texte)
    return bool(_STATUT_PUBLIC.search(t)) and not _CONTRACTUEL.search(t)
