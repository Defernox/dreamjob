"""Contrat commun à toutes les sources d'offres.

Ajouter une source = un fichier qui implémente `BaseConnector.fetch`, plus une
entrée dans `config.yaml`. Rien d'autre à toucher.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar


class ErreurConnecteur(RuntimeError):
    """Panne d'une source. Consignée dans ScanRun, n'interrompt jamais les autres."""


class ConnecteurNonConfigure(ErreurConnecteur):
    """Identifiants absents : la source est ignorée, ce n'est pas une panne."""


@dataclass(frozen=True)
class SearchQuery:
    """Ce qu'on demande à une source. Volontairement pauvre : le dénominateur
    commun de sites très différents. Le tri fin se fait après, au scoring."""

    mots_cles: list[str] = field(default_factory=list)
    pays: list[str] = field(default_factory=list)
    contrats: list[str] = field(default_factory=list)
    departement: str = ""
    publiee_depuis_jours: int | None = None
    max_offres: int = 150

    def en_dict(self) -> dict:
        return {
            "mots_cles": self.mots_cles,
            "pays": self.pays,
            "contrats": self.contrats,
            "departement": self.departement,
            "publiee_depuis_jours": self.publiee_depuis_jours,
            "max_offres": self.max_offres,
        }


@dataclass
class RawOffer:
    """Une offre telle que la source la donne, normalisée mais pas interprétée.

    Aucun score ici : le scoring est une étape séparée, sur le contenu stocké.
    """

    source: str
    source_id: str
    titre: str
    url: str = ""
    entreprise: str = ""
    lieu: str = ""
    pays: str = ""
    type_contrat: str = ""
    date_publication: datetime | None = None
    description_brute: str = ""
    raw: dict = field(default_factory=dict)


class BaseConnector(ABC):
    cle: ClassVar[str] = ""
    libelle: ClassVar[str] = ""

    def __init__(self, http, reglages) -> None:
        self.http = http
        self.reglages = reglages

    def verifier_configuration(self) -> None:
        """Lève ConnecteurNonConfigure si les identifiants manquent.

        Par défaut : rien à configurer.
        """

    @abstractmethod
    def fetch(self, query: SearchQuery) -> list[RawOffer]:
        """Récupère les offres. Doit lever ErreurConnecteur en cas de panne."""
