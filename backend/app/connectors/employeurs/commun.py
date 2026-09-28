"""Ce que tous les logiciels de recrutement partagent : l'annonce, le tri des
intitulés, le contrat deviné, le HTML rendu lisible."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape

from ...scoring.lexique import jetons
from ..base import SearchQuery


@dataclass
class Annonce:
    """Une offre telle qu'un site carrières la liste, puis la détaille.

    `ident` est l'identifiant stable chez l'employeur ; `complete` dit si la
    fiche a été ouverte (description, date exacte, pays sûr).
    """

    ident: str
    titre: str
    url: str
    lieu: str = ""
    pays: str = ""
    publiee_le: datetime | None = None
    contrat: str = ""
    description: str = ""
    # L'entité qui recrute, quand un site de groupe la nomme (« Natixis CIB »
    # sur le site du groupe BPCE) ; sinon, le nom de l'employeur suivi.
    entreprise: str = ""
    brut: dict = field(default_factory=dict)
    complete: bool = False


class Interdit(RuntimeError):
    """robots.txt interdit la page : on ne la demande pas."""


# --- Les intitulés ------------------------------------------------------------------


def cles(query: SearchQuery) -> list[frozenset[str]]:
    """Chaque expression de la recherche, en mots canoniques. Une recherche sans
    mot-clé ne demande rien : un site carrières entier n'est pas une recherche."""
    return [frozenset(jetons(m)) for m in query.mots_cles if jetons(m)]


def correspond(titre: str, recherches: list[frozenset[str]]) -> bool:
    """L'intitulé répond-il à l'une des recherches ?

    Les sites carrières ne cherchent pas pour nous : un site anglophone ne
    trouverait rien à « analyste risques ». On compare donc nous-mêmes, avec le
    vocabulaire du score — « Risk Analyst » et « analyste risques » donnent les
    mêmes mots. Tous les mots de la recherche doivent y être ; au-delà de deux,
    on en tolère un absent : « Analyste risques de crédit » doit trouver
    « Credit Risk Officer ».
    """
    mots = set(jetons(titre))
    for recherche in recherches:
        manquants = len(recherche - mots)
        if manquants == 0 or (len(recherche) >= 3 and manquants == 1):
            return True
    return False


# --- Le contrat ---------------------------------------------------------------------

_CONTRATS = [
    ("Alternance", re.compile(r"\b(?:alternan\w*|apprenti\w*|apprentice\w*|work[- ]study|dual[- ]study)\b", re.I)),
    ("Stage", re.compile(r"\b(?:stage|stagiaire|intern|internship|praktikum|praktikant\w*|tirocinio)\b", re.I)),
    ("V.I.E", re.compile(r"\bV\.?I\.?E\b|volontariat international")),
    ("CDD", re.compile(r"\bCDD\b|fixed[- ]term|\bFTC\b|temporary contract|befristet", re.I)),
    ("CDI", re.compile(r"\bCDI\b|\bpermanent\b|unbefristet", re.I)),
]


def contrat(*textes: str) -> str:
    """Le contrat que dit l'intitulé (ou un champ du site), sinon rien.

    Rien n'est pas « CDI » : laisser vide rend le critère non évaluable, là où
    une supposition fausserait le score — et le filtre des recherches.
    """
    for texte in textes:
        for nom, motif in _CONTRATS:
            if texte and motif.search(texte):
                return nom
    return ""


# --- Le texte -----------------------------------------------------------------------

_SAUTS = re.compile(r"(?i)<(?:br|/p|/li|/div|/h[1-6]|/tr)\b[^>]*>")
_PUCES = re.compile(r"(?i)<li\b[^>]*>")
_BALISES = re.compile(r"<[^>]+>")
_CODE = re.compile(r"(?is)<(script|style)\b.*?</\1>")


def texte(html: str | None) -> str:
    """HTML d'annonce en texte lisible, les fins de bloc gardées en sauts de
    ligne : sans elles, les puces se recollent et le score perd les phrases."""
    brut = _CODE.sub(" ", html or "")
    brut = _PUCES.sub("\n- ", _SAUTS.sub("\n", brut))
    nu = unescape(_BALISES.sub(" ", brut))
    lignes = [ligne.strip() for ligne in re.sub(r"[^\S\n]+", " ", nu).splitlines()]
    # « <b>risques</b>. » laissait « risques . » : une balise en ligne retirée
    # ne doit pas décoller la ponctuation.
    lignes = [re.sub(r" +([.,)])", r"\1", ligne) for ligne in lignes]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lignes)).strip()


def identifiant(nom: str) -> str:
    """« Crédit Agricole CIB » → « credit-agricole-cib » : préfixe des
    identifiants d'offre, stable tant que le nom ne change pas."""
    sans = unicodedata.normalize("NFKD", nom)
    sans = "".join(c for c in sans if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", sans).strip("-")
