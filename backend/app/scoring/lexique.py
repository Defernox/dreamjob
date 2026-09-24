"""Le vocabulaire commun au CV et aux offres : racines, synonymes, expressions.

Deux textes ne se comparent que s'ils ont été découpés de la même façon. Tout
ce qui compare un CV à une annonce passe donc par `jetons` : minuscules, sans
accents, mots vides retirés, chaque mot ramené à sa **forme canonique** — sa
famille de synonymes s'il en a une (« credit risk » et « risque de crédit »
deviennent les mêmes jetons), sa racine sinon (« financières » et « financier »,
« analyste » et « analyst »).

**Les expressions comptent plus que les mots.** « middle office » n'a rien à
voir avec « office manager », ni « risque de crédit » avec « crédit » tout court.
`bigrammes` relève les paires de mots voisins, sans ordre — « risque de crédit »
et « credit risk » donnent la même paire.
"""

from __future__ import annotations

from functools import lru_cache

from .synonymes import _EQUIVALENTS
from .texte import mots, normaliser

# --- Racines ----------------------------------------------------------------


def racine(mot: str) -> str:
    """Une racine grossière, mais la même des deux côtés : pluriels et féminins.

    Pas de vrai racinisateur : il faudrait une dépendance, et une racine
    agressive confond des mots de sens différents. On retire seulement le
    pluriel (-s, -x), le féminin (-ée → -é) et le -e final après consonne —
    assez pour que « financières » rencontre « financier », et « analyste »,
    « analyst ».
    """
    if len(mot) <= 3 or not mot.isalpha():
        return mot
    if mot[-1] in "sx" and not mot.endswith(("ss", "us", "is")):
        mot = mot[:-1]
    # Les féminins qui changent de suffixe : « directrice », « administrative »,
    # « technicienne », « vendeuse » retrouvent leur masculin.
    for feminin, masculin in (("trice", "teur"), ("euse", "eur"), ("ienne", "ien"),
                              ("ive", "if")):
        if mot.endswith(feminin) and len(mot) > len(feminin) + 2:
            return mot[: -len(feminin)] + masculin
    if mot.endswith("ee"):
        mot = mot[:-1]
    if len(mot) > 5 and mot.endswith("e") and mot[-2] not in "aeiouy":
        mot = mot[:-1]
    return mot


def _representants() -> dict[str, str]:
    """Mot (ou sa racine) -> représentant de sa famille de synonymes."""
    table: dict[str, str] = {}
    for famille in set(_EQUIVALENTS.values()):
        representant = racine(min(famille))
        for membre in famille:
            table.setdefault(membre, representant)
            table.setdefault(racine(membre), representant)
    return table


_REPRESENTANT = _representants()


@lru_cache(maxsize=20000)
def canon(mot: str) -> str:
    """La forme canonique d'un mot déjà normalisé."""
    return _REPRESENTANT.get(mot) or _REPRESENTANT.get(racine(mot)) or racine(mot)


# --- Jetons et expressions ------------------------------------------------------

# « P&L » perd son esperluette à la normalisation et deviendrait deux lettres
# isolées, jetées. On le réécrit avant.
_REECRITURES = (("p&l", " pnl "), ("m&a", " fusion acquisition "), ("fp&a", " fpa "))


def jetons(texte: str | None) -> list[str]:
    """Les mots porteurs de sens, dans l'ordre, sous leur forme canonique."""
    if not texte:
        return []
    brut = texte.lower()
    for motif, remplacement in _REECRITURES:
        brut = brut.replace(motif, remplacement)
    return [canon(m) for m in mots(brut)]


def bigrammes(suite: list[str]) -> set[str]:
    """Les paires de mots voisins, sans ordre : « a|b » avec a < b."""
    return {f"{min(a, b)}|{max(a, b)}" for a, b in zip(suite, suite[1:]) if a != b}


# --- Mots d'un intitulé qui ne disent rien du métier ---------------------------------

# Le contrat, le niveau, le genre, le rythme : chacun est jugé par son propre
# critère. Laissés dans l'intitulé, « CDI » ou « junior » feraient ressembler
# deux métiers sans rapport.
NEUTRES_INTITULE = {canon(normaliser(m)) for m in (
    "h", "f", "x", "m", "w", "d", "hf", "fh", "cdi", "cdd", "stage", "stagiaire",
    "alternance", "alternant", "apprenti", "apprentissage", "vie", "v.i.e", "interim",
    "freelance", "junior", "senior", "sr", "jr", "confirme", "experimente", "urgent",
    "temps", "plein", "partiel", "remote", "hybride", "hybrid", "teletravail", "full",
    "time", "part", "all", "genders", "gender", "contract", "permanent", "fixed", "term",
    "janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre",
    "octobre", "novembre", "decembre", "2025", "2026", "2027", "mois", "months",
    "month", "an", "ans", "year", "years", "ref", "reference", "poste", "job", "new",
    "annee", "annees", "erasmus",
    # Les restes de l'écriture inclusive : « administratif(ve) », « financier(ère) ».
    "ve", "ere", "eure", "trice", "rice", "euse", "ne", "e", "fe", "le",
    # Un diplôme n'est pas un métier : sans ceci, le « Master » d'un Master 2
    # rapprochait le CV d'un poste de « Scrum Master ».
    "master", "masters", "mba", "msc", "pge", "licence", "bachelor", "bts", "dut",
    "doctorat", "phd", "diplome", "programme",
)}

# Des mots qui habillent une compétence sans en porter aucune : « Connaissance du
# fonctionnement des différents produits », « Maîtrise du pack office ». Laissés
# dans le vocabulaire, ils rapprochaient le CV de toute annonce qui les emploie.
CREUX = {canon(normaliser(m)) for m in (
    "connaissance", "connaissances", "fonctionnement", "different", "differents",
    "differentes", "maitrise", "maitriser", "esprit", "codage", "pack", "capacite",
    "capacites", "bonne", "bonnes", "bon", "bons", "sens", "aisance", "qualite",
    "qualites", "savoir", "etre", "faire", "notion", "notions", "base", "bases",
    "niveau", "outils", "outil", "logiciel", "logiciels", "utilisation", "usage",
    "ensemble", "cadre", "sein", "afin", "ainsi", "tout", "toute", "tous", "toutes",
    "chaque", "tres", "bien", "fort", "forte", "leur", "vos", "nos", "mise", "place",
    "deux", "trois", "quatre", "cinq", "semaine", "semaines", "jour", "jours", "mois",
    "actuellement", "cours", "ecole",
)}


def jetons_intitule(titre: str | None, lieu: str | None = "") -> list[str]:
    """Les mots d'un intitulé qui disent le métier : sans contrat, sans niveau,
    sans genre, et sans le lieu (« Gestionnaire middle office - Montpellier »)."""
    du_lieu = set(jetons(lieu))
    return [j for j in jetons(titre)
            if j not in NEUTRES_INTITULE and j not in du_lieu and not j.isdigit()]
