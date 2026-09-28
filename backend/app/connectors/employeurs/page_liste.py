"""Une liste HTML paginée : La Banque Postale, Crédit Mutuel.

Des sites faits maison, sans logiciel reconnu ni plan du site, mais qui
publient la liste de leurs offres en pages numérotées, avec l'intitulé dans
le lien. Options dans employeurs.yaml :

- `liste` : l'adresse d'une page de liste, `{page}` pour son numéro (sans lui,
  une seule page) ;
- `offres` : motif que suit le lien d'une offre ; `identifiant` : motif dont
  le premier groupe identifie l'offre ;
- pour la fiche, les mêmes que le plan du site (`bloc`, `fin_bloc`,
  `titre_h1`) : elle se lit de la même façon.

Vérifié le 2026-09-29. Crédit Mutuel : robots.txt interdit les paramètres de
navigation (`_tabi`, `_pid`, `_fid`) — seule la première page, les offres les
plus récentes, est lue.
"""

from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from urllib.parse import urljoin, urlparse

from .commun import Annonce, contrat
from .plan_du_site import PlanDuSite, titre_de_l_adresse
from .registre import Employeur

_LIEN = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
# Le bouton à côté de l'intitulé mène à la même offre : son libellé n'en est pas un.
_GENERIQUE = re.compile(r"^(?:d[ée]tails?(?: de l'offre)?|voir(?: l'offre| plus)?|en savoir plus|postuler|"
                        r"read more|view(?: job)?|apply|plus d'infos?)$", re.I)


def _propre(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment or "")).split())


class PageListe(PlanDuSite):
    cle = "page_liste"

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        modele = str(employeur.options["liste"])
        motif = re.compile(employeur.options["offres"], re.I)
        identifiant = employeur.options.get("identifiant")
        vues: dict[str, Annonce] = {}
        for page in range(1, pages_max + 1):
            url = modele.format(page=page) if "{page}" in modele else modele
            self.verifier(url)
            html = self.http.get(url, utiliser_cache=False).texte or ""
            nouvelles = 0
            for href, texte_lien in _LIEN.findall(html):
                cible = urljoin(url, unescape(href.strip()))
                if not motif.search(cible):
                    continue
                m = re.search(identifiant, cible) if identifiant else None
                ident = m.group(1) if m else urlparse(cible).path.rstrip("/").rsplit("/", 1)[-1]
                texte_ = _propre(texte_lien)
                titre = texte_ if texte_ and not _GENERIQUE.match(texte_) else ""
                if ident in vues:
                    # Deux liens vers la même offre : l'intitulé, le plus long, l'emporte.
                    if len(titre) > len(vues[ident].titre) or not vues[ident].titre:
                        vues[ident].titre = titre or vues[ident].titre
                    continue
                vues[ident] = Annonce(ident=ident, titre=titre, url=cible)
                nouvelles += 1
            if "{page}" not in modele or nouvelles == 0:
                break
        for a in vues.values():
            a.titre = a.titre or titre_de_l_adresse(a.url, identifiant)
            a.contrat = contrat(a.titre)
        return list(vues.values())
