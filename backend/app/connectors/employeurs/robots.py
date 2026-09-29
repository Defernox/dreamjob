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

Au-delà des chemins, un site peut dire ce qu'il permet de faire de son contenu
(`Content-Signal`, voir `Regles.usages_permis`) : c'est respecté aussi.
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
        # Hors norme, mais répandu : « Crawl-delay: 5 » (AXA). On le respecte.
        self.delai: float | None = None
        # « Content-Signal: search=no, ai-input=no » (Cloudflare, 2025) : ce que
        # le site permet de faire de son contenu. Voir `usages_permis`.
        self.signaux: dict[str, str] = {}
        groupes: list[tuple[list[str], list[tuple[bool, str]]]] = []
        delais: dict[int, float] = {}
        signaux: dict[int, dict[str, str]] = {}
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
            elif cle == "crawl-delay":
                # Cornerstone (afd.csod.com) écrit « Crawl-delay: 10 » seul, hors
                # de tout groupe : la demande vaut pour tous, on la respecte.
                dans_les_agents = False
                try:
                    delais[len(groupes) - 1 if groupes else -1] = float(valeur)
                except ValueError:
                    pass
            elif cle == "content-signal":
                dans_les_agents = False
                cible = signaux.setdefault(len(groupes) - 1 if groupes else -1, {})
                for paire in valeur.split(","):
                    if "=" in paire:
                        nom_, oui_non = (x.strip().lower() for x in paire.split("=", 1))
                        cible[nom_] = oui_non
        nom = agent.lower()
        # Le nom du robot, exactement : « autre » ne vise pas « AutreRobot ».
        propres = [i for i, (a, _) in enumerate(groupes) if nom in a]
        communes = [i for i, (a, _) in enumerate(groupes) if "*" in a]
        choisis = propres or communes
        self.regles = [regle for i in choisis for regle in groupes[i][1]]
        delais_choisis = [delais[i] for i in [-1, *choisis] if i in delais]
        self.delai = max(delais_choisis) if delais_choisis else None
        for i in [-1, *choisis]:
            self.signaux.update(signaux.get(i, {}))

    def usages_permis(self) -> bool:
        """DreamJob fait deux des trois usages que nomme Content-Signal : il
        range les offres pour les chercher (`search`) et en donne la
        description à un modèle pour écrire la lettre (`ai-input`). Il n'en
        entraîne aucun (`ai-train` ne le concerne pas). Un site qui refuse l'un
        des deux n'est pas collecté — Antin Infrastructure Partners déclare
        `search=no, ai-input=no`."""
        return self.signaux.get("search") != "no" and self.signaux.get("ai-input") != "no"

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
                if regles.delai and hasattr(self.http, "ralentir"):
                    self.http.ralentir(p.netloc, regles.delai)
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
        return regles is not None and regles.usages_permis() and regles.autorise(url)
