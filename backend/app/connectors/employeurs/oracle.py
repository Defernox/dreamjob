"""Oracle Recruiting Cloud : J.P. Morgan, BNY, SCOR, Lazard, Schroders, Citco.

Chaque site (`<hôte>.oraclecloud.com/hcmUI/CandidateExperience/<langue>/sites/<site>`)
s'alimente à l'interface REST publique d'Oracle, celle que la page appelle.
Vérifié le 2026-09-28 sur jpmc.fa.oraclecloud.com :

- `robots.txt` répond 403 à tout le monde, navigateurs compris : selon la
  RFC 9309, rien n'est interdit ;
- la liste se trie par date (`sortBy=POSTING_DATES_DESC`), deux cents offres
  par page au plus — J.P. Morgan en publie environ deux cents par jour : la
  veille lit une page, le scan d'un mois une vingtaine ;
- le filtre par lieu n'est pas fiable (la liste des pays est tronquée à
  quarante lieux, et la France n'y figure pas face aux États américains) : on
  filtre ici, sur le code ISO du lieu principal et des lieux secondaires ;
- la fiche donne la description, la date à la seconde, le type de poste.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote, urlparse

from .commun import Annonce, contrat, texte
from .logiciel import Logiciel
from .pays import depuis_iso, depuis_lieu
from .registre import Employeur

PAR_PAGE = 200
API = "/hcmRestApi/resources/latest"


def adresses(employeur: Employeur) -> tuple[str, str, str]:
    """(hôte, numéro de site, langue) d'après l'adresse du site carrières."""
    p = urlparse(employeur.adresse)
    m = re.search(r"/CandidateExperience/([a-z]{2}(?:-[A-Z]{2})?)/sites/([^/?#]+)", p.path)
    if not m:
        raise ValueError(f"Adresse Oracle sans site : {employeur.adresse}")
    return f"https://{p.netloc}", m.group(2), m.group(1)


def _date(valeur: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((valeur or "")[:19]) if valeur else None
    except ValueError:
        return None


class Oracle(Logiciel):
    cle = "oracle"

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        hote, site, langue = adresses(employeur)
        annonces: list[Annonce] = []
        for page in range(pages_max):
            url = (f"{hote}{API}/recruitingCEJobRequisitions?onlyData=true"
                   f"&expand=requisitionList.secondaryLocations"
                   f"&finder=findReqs;siteNumber={site},limit={PAR_PAGE},offset={page * PAR_PAGE},"
                   f"sortBy=POSTING_DATES_DESC")
            self.verifier(url)
            r = self.http.get(url, entetes={"Accept": "application/json"}, utiliser_cache=False, revalider=True)
            items = (r.json_ or {}).get("items") or [] if isinstance(r.json_, dict) else []
            offres = (items[0].get("requisitionList") or []) if items else []
            trop_vieille = False
            for o in offres:
                publiee = _date(o.get("PostedDate"))
                if publiee is not None and publiee < depuis.replace(hour=0, minute=0, second=0):
                    trop_vieille = True
                    break
                # Un poste à New York et à Paris est retenu pour Paris.
                lieux = [depuis_iso(o.get("PrimaryLocationCountry"))] + [
                    depuis_iso(s.get("CountryCode")) for s in o.get("secondaryLocations") or []]
                lieux = [p for p in lieux if p]
                retenu = next((p for p in lieux if p in pays), lieux[0] if lieux else "")
                lieu = o.get("PrimaryLocation") or ""
                annonces.append(Annonce(
                    ident=str(o.get("Id")),
                    titre=(o.get("Title") or "").strip(),
                    url=f"{hote}/hcmUI/CandidateExperience/{langue}/sites/{site}/job/{o.get('Id')}",
                    lieu=lieu, pays=retenu or depuis_lieu(lieu), publiee_le=publiee,
                    contrat=contrat(o.get("Title") or ""),
                    brut={"site": site},
                ))
            if trop_vieille or len(offres) < PAR_PAGE:
                break
        return [a for a in annonces if a.titre and not (pays and a.pays and a.pays not in pays)]

    def completer(self, employeur: Employeur, annonce: Annonce) -> Annonce:
        hote, site, _ = adresses(employeur)
        url = (f"{hote}{API}/recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
               f"&finder=ById;Id={quote(chr(34) + annonce.ident + chr(34))},siteNumber={site}")
        self.verifier(url)
        r = self.http.get(url, entetes={"Accept": "application/json"})
        items = (r.json_ or {}).get("items") or [] if isinstance(r.json_, dict) else []
        if not items:
            return annonce
        i = items[0]
        parties = [i.get(c) for c in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr",
                                      "ExternalQualificationsStr") if i.get(c)]
        annonce.description = texte("\n".join(parties))
        annonce.lieu = i.get("PrimaryLocation") or annonce.lieu
        annonce.pays = annonce.pays or depuis_iso(i.get("PrimaryLocationCountry")) or depuis_lieu(annonce.lieu)
        annonce.publiee_le = _date(i.get("ExternalPostedStartDate")) or annonce.publiee_le
        annonce.contrat = contrat(annonce.titre, i.get("ContractType") or "",
                                  i.get("RequisitionType") or "") or annonce.contrat
        annonce.complete = True
        return annonce
