"""robots.txt, relu à chaque scan : ce qu'un site interdit demain, on cesse de
le demander demain.

**La lecture suit la norme (RFC 9309), pas `urllib.robotparser`.** Le module
standard applique la première règle rencontrée ; la norme veut la plus
précise — le motif le plus long —, l'autorisation l'emportant à égalité. Sur
morganstanley.eightfold.ai (`Disallow: /` puis `Allow: /api/pcsx`), le module
standard interdisait ce que le site autorise en toutes lettres ; l'inverse
peut arriver aussi, et laisserait passer une interdiction.

Et pour le fichier lui-même :

- présent : ses règles s'appliquent, au groupe qui nomme notre robot, sinon au
  groupe `*` ;
- 4xx (absent, ou refusé à tous) : rien n'est interdit. Oracle renvoie 403 à
  tout le monde, navigateurs compris — ce n'est pas un refus qui nous vise ;
- 5xx ou serveur injoignable : on s'abstient, faute de savoir.
"""

from __future__ import annotations

import logging
import re
import threading
from urllib.parse import unquote, urlparse

import httpx

from ..http import ClientHttp, ErreurHttp

log = logging.getLogger("dreamjob.employeurs")


class Regles:
    """Les règles d'un robots.txt pour un robot donné."""

    def __init__(self, texte: str, agent: str) -> None:
        self.regles: list[tuple[bool, str]] = []
        self.plans: list[str] = []
        groupes: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents: list[str] = []
        regles: list[tuple[bool, str]] = []
        dans_les_agents = False
        for ligne in texte.splitlines():
            ligne = ligne.split("#", 1)[0].strip()
            if ":" not in ligne:
                continue
            cle, valeur = (x.strip() for x in ligne.split(":", 1))
            cle = cle.lower()
            if cle == "sitemap":
                self.plans.append(valeur)
            elif cle == "user-agent":
                if not dans_les_agents:
                    agents, regles = [], []
                    groupes.append((agents, regles))
                agents.append(valeur.lower())
                dans_les_agents = True
            elif cle in ("allow", "disallow"):
                dans_les_agents = False
                if groupes and valeur:
                    regles.append((cle == "allow", valeur))
                # « Disallow: » vide n'interdit rien : aucune règle à ajouter.
        nom = agent.lower()
        # Le nom du robot, exactement : « autre » ne vise pas « AutreRobot ».
        propres = [r for a, r in groupes if nom in a]
        communes = [r for a, r in groupes if "*" in a]
        choisis = propres or communes
        self.regles = [regle for groupe in choisis for regle in groupe]

    @staticmethod
    def _motif(chemin: str) -> re.Pattern:
        fin = chemin.endswith("$")
        corps = re.escape(unquote(chemin.rstrip("$"))).replace(r"\*", ".*")
        return re.compile(corps + ("$" if fin else ""))

    def autorise(self, url: str) -> bool:
        p = urlparse(url)
        chemin = unquote(p.path or "/") + (f"?{unquote(p.query)}" if p.query else "")
        meilleure: tuple[int, bool] | None = None
        for autorise, motif in self.regles:
            if self._motif(motif).match(chemin):
                cle = (len(motif), autorise)       # le plus long, puis Allow à égalité
                if meilleure is None or cle > meilleure:
                    meilleure = cle
        return True if meilleure is None else meilleure[1]

    def site_maps(self) -> list[str]:
        return list(self.plans)


class Robots:
    def __init__(self, http: ClientHttp, agent: str) -> None:
        self.http = http
        # Les règles visent le nom du robot, pas sa version ni son adresse.
        self.agent = agent.split("/")[0].strip() or "*"
        self._regles: dict[str, Regles | None] = {}
        self._verrou = threading.Lock()

    def _pour(self, url: str) -> Regles | None:
        p = urlparse(url)
        origine = f"{p.scheme}://{p.netloc.lower()}"
        with self._verrou:
            if origine in self._regles:
                return self._regles[origine]
        regles: Regles | None
        try:
            r = self.http.get(f"{origine}/robots.txt", statuts_acceptes=tuple(range(200, 600)))
            if r.statut >= 500:
                log.warning("robots.txt de %s en erreur %d : on s'abstient", origine, r.statut)
                regles = None
            else:
                regles = Regles(r.texte if r.statut == 200 else "", self.agent)
        except ErreurHttp as e:
            log.warning("robots.txt de %s injoignable : on s'abstient (%s)", origine, e)
            regles = None
        except (httpx.InvalidURL, httpx.HTTPError, ValueError) as e:
            # Une adresse malformée dans employeurs.yaml : on s'abstient.
            log.warning("robots.txt de %s illisible : on s'abstient (%s)", origine, e)
            regles = None
        with self._verrou:
            self._regles[origine] = regles
        return regles

    def autorise(self, url: str) -> bool:
        regles = self._pour(url)
        return regles is not None and regles.autorise(url)
