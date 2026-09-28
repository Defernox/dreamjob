"""Le contrat d'un logiciel de recrutement : lister, puis détailler.

Lister coûte peu (une page donne vingt offres ou plus) et se fait pour chaque
employeur à chaque scan ; détailler coûte une requête par offre, et ne se fait
que pour les offres nouvelles qui répondent à une recherche.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import ClassVar

from ..http import ClientHttp
from .commun import Annonce, Interdit
from .registre import Employeur
from .robots import Robots


class Logiciel(ABC):
    cle: ClassVar[str] = ""

    def __init__(self, http: ClientHttp, robots: Robots) -> None:
        self.http = http
        self.robots = robots

    def verifier(self, url: str) -> None:
        if not self.robots.autorise(url):
            raise Interdit(f"robots.txt interdit {url}")

    @abstractmethod
    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        """Les offres publiées depuis `depuis`, dans ces pays (tous si la liste
        est vide), de la plus récente à la plus ancienne."""

    def completer(self, employeur: Employeur, annonce: Annonce) -> Annonce:
        """Ouvre la fiche : description, date exacte, pays sûr. Par défaut, la
        liste suffisait."""
        annonce.complete = True
        return annonce
