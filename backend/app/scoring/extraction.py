"""Signaux tirés d'une offre — **sans aucun appel LLM**.

Tout ce qui est calculé ici ne dépend que de l'offre, jamais du profil : le
résultat est donc mis en cache dans `Offer.extraction` et ne se recalcule pas
quand les poids changent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..models import Offer
from .langue import detecter, langues_exigees
from .rome import domaine
from .texte import ensemble_mots, normaliser

# Version des règles d'extraction. L'incrémenter force un recalcul des signaux :
# `services/scoring.py` sélectionne aussi les offres dont les signaux stockés
# portent une autre version. Sans ce filtre, l'incrément ne servait à rien — une
# offre déjà scorée n'était jamais revisitée et gardait ses signaux périmés.
# 2 : ajout des langues exigées par l'annonce.
VERSION = 2


@dataclass
class Signaux:
    langue: str = ""
    # Codes ISO des langues que l'annonce réclame explicitement — distinct de
    # la langue dans laquelle elle est rédigée.
    exigences_langues: list[str] = field(default_factory=list)
    # Texte servant à reconnaître le secteur : intitulé, libellé ROME, domaine.
    texte_secteur: str = ""
    # Vocabulaire complet de l'offre, pour la recherche de compétences.
    vocabulaire: list[str] = field(default_factory=list)
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

    texte_secteur = " ".join(filter(None, [
        offre.titre, rome_libelle, appellation, domaine(brute.get("romeCode")),
    ]))

    # La langue se juge sur la description : un intitulé est trop court, et
    # souvent en anglais même dans une offre française. Un repli sur le titre
    # figurait ici : il ne s'est jamais déclenché — un intitulé compte 6 à 10
    # jetons quand `MOTS_MINIMUM` en exige 12 — tout en étant calculé à chaque
    # appel. Une description trop courte laisse la langue non évaluée, et un
    # critère non évaluable ne pénalise pas l'offre.
    langue = detecter(offre.description_brute)

    vocabulaire = ensemble_mots(f"{offre.titre} {rome_libelle} {appellation} "
                                f"{offre.description_brute}")

    return Signaux(
        langue=langue,
        exigences_langues=langues_exigees(
            f"{offre.titre} {offre.description_brute}"
        ),
        texte_secteur=normaliser(texte_secteur),
        vocabulaire=sorted(vocabulaire),
    )


def signaux_de(offre: Offer) -> Signaux:
    """Signaux de l'offre, depuis le cache si la version correspond."""
    en_cache = Signaux.depuis_dict(offre.extraction)
    if en_cache is not None:
        return en_cache
    return extraire(offre)
