"""Ce que les offres ont en commun — pour savoir quels mots distinguent.

Un mot présent dans une annonce sur deux ne dit presque rien d'une annonce en
particulier ; un mot présent dans une sur cent la caractérise. C'est la
fréquence documentaire inverse (IDF), calculée sur les offres du compte : dans
un fil nourri de recherches en finance, « financier » est banal et ne doit plus
suffire à rapprocher un poste de comptable d'un CV de marchés, alors que
« titrisation » ou « middle office » disent vraiment le métier.

Le corpus est recalculé à chaque scoring, en une fraction de seconde. Il évolue
avec les offres : c'est une entrée du score, comme la date du jour pour la
fraîcheur, et un score stocké est de toute façon recalculé chaque jour.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from .extraction import Signaux


@dataclass
class Corpus:
    nb_offres: int = 0
    intitules: Counter = field(default_factory=Counter)   # jetons et expressions des intitulés
    corps: Counter = field(default_factory=Counter)       # jetons et expressions des annonces

    @classmethod
    def depuis(cls, signaux: Iterable[Signaux]) -> "Corpus":
        corpus = cls()
        for s in signaux:
            corpus.nb_offres += 1
            corpus.intitules.update(set(s.intitule) | set(s.intitule_bigrammes))
            corpus.corps.update(set(s.corps) | set(s.corps_bigrammes))
        return corpus

    def _idf(self, compteur: Counter, terme: str) -> float:
        """IDF lissée, de 1 (partout) à ~1 + ln(N) (nulle part ailleurs).

        Sans corpus — un score calculé isolément, dans un test — tous les mots
        pèsent 1 et seule la pondération des mots génériques joue.
        """
        if self.nb_offres == 0:
            return 1.0
        return 1.0 + math.log((self.nb_offres + 1) / (compteur.get(terme, 0) + 1))

    def idf_intitule(self, terme: str) -> float:
        return self._idf(self.intitules, terme)

    def idf_corps(self, terme: str) -> float:
        return self._idf(self.corps, terme)

    def frequence_corps(self, terme: str) -> int:
        """Dans combien d'annonces le terme apparaît. Sans corpus : inconnu,
        on le suppose établi."""
        return self.corps.get(terme, 0) if self.nb_offres else ETABLI

    def etabli(self, terme: str, minimum: int) -> bool:
        """Le terme revient-il dans assez d'annonces pour être un vrai terme du
        métier ? Un mot ou une expression vus une seule fois sont presque
        toujours un nom propre, une coquille ou un voisinage fortuit
        (« autonome, méthodique ») — et leur rareté leur donnait le poids le
        plus fort."""
        # Sur un petit fil (un compte qui démarre), exiger trois annonces
        # viderait tout : le seuil suit la taille du corpus.
        return self.frequence_corps(terme) >= min(minimum, 1 + self.nb_offres // 200)


# Sans corpus, tout terme est tenu pour établi.
ETABLI = 10**9


NEUTRE = Corpus()
