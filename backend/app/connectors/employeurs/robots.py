"""robots.txt, relu à chaque scan : ce qu'un site interdit demain, on cesse de
le demander demain.

La sémantique est celle de la norme (RFC 9309), pas celle, plus ancienne, du
module `urllib.robotparser` :

- fichier présent : ses règles s'appliquent ;
- 4xx (absent, ou refusé à tous) : rien n'est interdit. Oracle renvoie 403 à
  tout le monde, navigateurs compris — ce n'est pas un refus qui nous vise ;
- 5xx ou serveur injoignable : on s'abstient, faute de savoir.
"""

from __future__ import annotations

import logging
import threading
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from ..http import ClientHttp, ErreurHttp

log = logging.getLogger("dreamjob.employeurs")


class Robots:
    def __init__(self, http: ClientHttp, agent: str) -> None:
        self.http = http
        # Les règles visent le nom du robot, pas sa version ni son adresse.
        self.agent = agent.split("/")[0].strip() or "*"
        self._regles: dict[str, RobotFileParser | None] = {}
        self._verrou = threading.Lock()

    def _pour(self, url: str) -> RobotFileParser | None:
        p = urlparse(url)
        origine = f"{p.scheme}://{p.netloc.lower()}"
        with self._verrou:
            if origine in self._regles:
                return self._regles[origine]
        regles: RobotFileParser | None
        try:
            r = self.http.get(f"{origine}/robots.txt", statuts_acceptes=tuple(range(200, 600)))
            if r.statut >= 500:
                log.warning("robots.txt de %s en erreur %d : on s'abstient", origine, r.statut)
                regles = None
            else:
                regles = RobotFileParser()
                regles.parse(r.texte.splitlines() if r.statut == 200 else [])
        except ErreurHttp as e:
            log.warning("robots.txt de %s injoignable : on s'abstient (%s)", origine, e)
            regles = None
        with self._verrou:
            self._regles[origine] = regles
        return regles

    def autorise(self, url: str) -> bool:
        regles = self._pour(url)
        return regles is not None and regles.can_fetch(self.agent, url)
