"""Signaux tirés d'une offre — **sans aucun appel LLM**.

Tout ce qui est calculé ici ne dépend que de l'offre, jamais du profil : le
résultat est donc mis en cache dans `Offer.extraction` et ne se recalcule pas
quand les poids changent.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field

from ..models import Offer
from .exigences import (
    annees_exigees,
    certifications_exigees,
    niveau_intitule,
    niveaux_etudes,
    statut_public_exige,
)
from .langue import detecter, langues_exigees
from .lexique import bigrammes, jetons, jetons_intitule
from .rome import domaine
from .texte import ensemble_mots, normaliser

# Version des règles d'extraction. L'incrémenter force un recalcul des signaux :
# `services/scoring.py` sélectionne aussi les offres dont les signaux stockés
# portent une autre version. Sans ce filtre, l'incrément ne servait à rien — une
# offre déjà scorée n'était jamais revisitée et gardait ses signaux périmés.
# 2 : ajout des langues exigées par l'annonce.
# 3 : intitulé et corps en jetons canoniques, expressions, exigences (niveau,
#     années, diplômes, certifications, statut public).
VERSION = 3


@dataclass
class Signaux:
    langue: str = ""
    # Codes ISO des langues que l'annonce réclame explicitement — distinct de
    # la langue dans laquelle elle est rédigée.
    exigences_langues: list[str] = field(default_factory=list)
    # Texte servant à reconnaître le secteur : intitulé, libellé ROME, domaine.
    texte_secteur: str = ""
    # Vocabulaire complet de l'offre (mots normalisés), pour la couverture des
    # documents et l'ordre des puces du CV.
    vocabulaire: list[str] = field(default_factory=list)

    # --- Pour le score -------------------------------------------------------
    # Les mots de l'intitulé qui disent le métier (jetons canoniques), et ses
    # expressions. L'appellation France Travail s'y ajoute : c'est le nom exact
    # du métier dans le répertoire ROME.
    intitule: list[str] = field(default_factory=list)
    intitule_bigrammes: list[str] = field(default_factory=list)
    # Le grand domaine ROME, en jetons : un recours quand l'intitulé est vague.
    rome: list[str] = field(default_factory=list)
    # Le corps de l'annonce : combien de fois chaque jeton canonique apparaît —
    # un mot répété est un mot sur lequel l'annonce insiste.
    corps: dict[str, int] = field(default_factory=dict)
    corps_bigrammes: list[str] = field(default_factory=list)
    niveau_poste: str = "intermediaire"
    annees_exigees: int | None = None
    etudes: list[int] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    statut_public: bool = False
    version: int = VERSION

    def en_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def depuis_dict(cls, donnees: dict | None) -> "Signaux | None":
        if not donnees or donnees.get("version") != VERSION:
            return None
        try:
            return cls(**donnees)
        except TypeError:
            return None


def extraire(offre: Offer) -> Signaux:
    brute = offre.raw or {}
    rome_libelle = brute.get("romeLibelle") or ""
    appellation = brute.get("appellationlibelle") or ""
    description = offre.description_brute or ""

    texte_secteur = " ".join(filter(None, [
        offre.titre, rome_libelle, appellation, domaine(brute.get("romeCode")),
    ]))

    # La langue se juge sur la description : un intitulé est trop court, et
    # souvent en anglais même dans une offre française. Une description trop
    # courte laisse la langue non évaluée, et un critère non évaluable ne
    # pénalise pas l'offre.
    langue = detecter(description)

    vocabulaire = ensemble_mots(f"{offre.titre} {rome_libelle} {appellation} {description}")

    intitule = jetons_intitule(offre.titre, offre.lieu)
    # L'appellation complète l'intitulé sans le répéter.
    intitule += [j for j in jetons_intitule(appellation, offre.lieu) if j not in intitule]

    suite_corps = jetons(description)
    texte_complet = f"{offre.titre} {description}"

    return Signaux(
        langue=langue,
        exigences_langues=langues_exigees(texte_complet),
        texte_secteur=normaliser(texte_secteur),
        vocabulaire=sorted(vocabulaire),
        intitule=intitule,
        intitule_bigrammes=sorted(bigrammes(intitule)),
        rome=jetons(rome_libelle),
        corps=dict(Counter(suite_corps)),
        corps_bigrammes=sorted(bigrammes(suite_corps)),
        niveau_poste=niveau_intitule(offre.titre),
        annees_exigees=annees_exigees(texte_complet),
        etudes=niveaux_etudes(description),
        certifications=certifications_exigees(description),
        statut_public=statut_public_exige(description),
    )


def signaux_de(offre: Offer) -> Signaux:
    """Signaux de l'offre, depuis le cache si la version correspond."""
    en_cache = Signaux.depuis_dict(offre.extraction)
    if en_cache is not None:
        return en_cache
    return extraire(offre)
