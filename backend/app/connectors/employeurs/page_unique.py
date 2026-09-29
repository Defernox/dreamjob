"""Toutes les offres sur une seule page, texte compris : Ofi Invest.

Certains sites faits maison publient leurs offres d'un bloc : une page, un
onglet par offre, la description entière dedans. Il n'y a rien à ouvrir de
plus — la liste est la fiche. Options dans employeurs.yaml :

- `liste` : l'adresse de la page ;
- `decoupe` : le repère qui ouvre chaque offre (« class="tab-pane ») ;
- `titre_motif` : motif dont le premier groupe est l'intitulé (le premier
  titre `<h1>`…`<h3>` du morceau sinon) ; `lieu_motif`, `contrat_motif` : de
  même pour le lieu et le contrat, quand ils ne suivent pas une étiquette ;
- `offres` : motif du lien propre à l'offre, s'il y en a un (son adresse et
  son identifiant) ; `identifiant` : motif dont le premier groupe identifie
  l'offre dans ce lien.

Une date limite de candidature écrite dans l'offre (« Date limite de dépôt de
candidature : 07/04/2026 ») est relevée : passée, l'offre n'est plus à
proposer, même si le site la laisse en ligne.
"""

from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from urllib.parse import urljoin

from .commun import Annonce, contrat, identifiant, texte
from .pays import depuis_lieu
from .plan_du_site import _CONTRAT_ETIQUETTE, _LIEU_ETIQUETTE, PlanDuSite
from .registre import Employeur

_TITRE = re.compile(r"<h[1-3][^>]*>(.*?)</h[1-3]>", re.S | re.I)
_LIEN = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.I)
_JJ_MM_AAAA = r"[^0-9]{0,60}?(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})"
_DATE_LIMITE = re.compile(r"(?:date\s+limite|deadline|closing\s+date|apply\s+by)" + _JJ_MM_AAAA, re.I)
_DATE_PARUTION = re.compile(r"(?:date\s+de\s+(?:parution|publication)|publi[ée]e?\s+le|posted\s+on)"
                            + _JJ_MM_AAAA, re.I)


def _propre(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment or "")).split())


def _jour(motif: re.Pattern, texte_: str) -> datetime | None:
    if m := motif.search(texte_ or ""):
        jour, mois, annee = (int(x) for x in m.groups())
        try:
            return datetime(annee, mois, jour)
        except ValueError:
            return None
    return None


def date_limite(texte_: str) -> str | None:
    """« Date limite de dépôt de candidature : 07/04/2026 » → « 2026-04-07 »."""
    jour = _jour(_DATE_LIMITE, texte_)
    return jour.date().isoformat() if jour else None


class PageUnique(PlanDuSite):
    cle = "page_unique"

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        o = employeur.options
        url = str(o["liste"])
        self.verifier(url)
        html = self.http.get(url, utiliser_cache=False, revalider=True).texte or ""
        morceaux = html.split(str(o["decoupe"]))[1:]
        vues: dict[str, Annonce] = {}
        for morceau in morceaux:
            m = re.search(o["titre_motif"], morceau, re.S) if o.get("titre_motif") else _TITRE.search(morceau)
            titre = _propre(m.group(1)) if m else ""
            if not titre:
                continue
            lien = next((urljoin(url, unescape(h)) for h in _LIEN.findall(morceau)
                         if o.get("offres") and re.search(o["offres"], h)), "")
            ident_m = re.search(o["identifiant"], lien) if o.get("identifiant") and lien else None
            ident = ident_m.group(1) if ident_m else identifiant(titre)
            corps = texte(morceau[morceau.find(">") + 1:])
            # Ofi Invest n'écrit pas « Lieu : » mais une icône puis la ville :
            # `lieu_motif` et `contrat_motif` le disent, un groupe chacun.
            lieu_m = (re.search(o["lieu_motif"], morceau, re.S) if o.get("lieu_motif")
                      else _LIEU_ETIQUETTE.search(morceau))
            lieu = _propre(lieu_m.group(1)) if lieu_m else ""
            type_m = (re.search(o["contrat_motif"], morceau, re.S) if o.get("contrat_motif")
                      else _CONTRAT_ETIQUETTE.search(morceau))
            pays_ = depuis_lieu(lieu) or depuis_lieu(titre) or o.get("pays_par_defaut", "")
            if pays and pays_ and pays_ not in pays:
                continue
            publiee = _jour(_DATE_PARUTION, corps)
            if publiee is not None and publiee < depuis.replace(hour=0, minute=0, second=0):
                continue
            annonce = Annonce(
                ident=ident, titre=titre, url=lien or url, lieu=lieu, pays=pays_, publiee_le=publiee,
                contrat=contrat(titre, unescape(type_m.group(1)) if type_m else "", corps[:600]),
                description=corps, complete=True)
            annonce.brut["date_limite"] = date_limite(corps)
            vues.setdefault(ident, annonce)
        return list(vues.values())

    def completer(self, employeur: Employeur, annonce: Annonce) -> Annonce:
        # La page portait déjà tout : rien à ouvrir.
        annonce.complete = True
        return annonce
