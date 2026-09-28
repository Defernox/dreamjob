"""Eightfold : Morgan Stanley, HSBC.

`robots.txt` d'Eightfold interdit tout sauf, explicitement, `/careers`,
`/api/apply` et `/api/pcsx` — les interfaces que la page appelle. Deux
générations coexistent (vérifié le 2026-09-28) :

- **`/api/pcsx/search`** (Morgan Stanley) : liste triée par date
  (`sort_by=timestamp`), dix offres par page quelle que soit la taille
  demandée ; la fiche par `/api/pcsx/position_details` ;
- **`/api/apply/v2/jobs`** (HSBC) : sans lieu, elle choisit celui de l'appelant
  d'après son adresse — un serveur en Allemagne n'y verrait pas les mêmes
  offres qu'un PC à Paris. On l'interroge donc **pays par pays**
  (`par_pays: true`), en nommant chacun en anglais.

L'API veut le domaine de l'entreprise (`domaine` dans employeurs.yaml).
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from .commun import Annonce, contrat, texte
from .logiciel import Logiciel
from .pays import en_anglais, pays_possibles
from .registre import Employeur

PAR_PAGE = 10
# Des pages de dix : cinq fois le plafond commun pour lire autant d'offres.
FACTEUR_PAGES = 5


def _base(employeur: Employeur) -> tuple[str, str]:
    racine = employeur.adresse.rstrip("/").split("/careers")[0]
    domaine = employeur.options.get("domaine")
    if not domaine:
        raise ValueError(f"Eightfold sans domaine : {employeur.nom}")
    return racine, str(domaine)


def _depuis_epoch(valeur) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(valeur), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


class Eightfold(Logiciel):
    cle = "eightfold"

    def _pages(self, url_de, depuis: datetime, pays: list[str], pages: int,
               cle_date: str, cle_liste: str) -> list[Annonce]:
        annonces: list[Annonce] = []
        for page in range(pages):
            url = url_de(page * PAR_PAGE)
            self.verifier(url)
            r = self.http.get(url, entetes={"Accept": "application/json"}, utiliser_cache=False)
            corps = r.json_ if isinstance(r.json_, dict) else {}
            positions = (corps.get("data") or corps).get(cle_liste) or []
            trop_vieille = False
            for p in positions:
                publiee = _depuis_epoch(p.get(cle_date))
                if publiee is not None and publiee < depuis.replace(hour=0, minute=0, second=0):
                    trop_vieille = True
                    break
                lieux = p.get("locations") or ([p["location"]] if p.get("location") else [])
                possibles = [x for lieu in lieux for x in pays_possibles(lieu)]
                if pays and possibles and not set(possibles) & set(pays):
                    continue
                chemin = p.get("canonicalPositionUrl") or p.get("positionUrl") or f"/careers/job/{p.get('id')}"
                annonces.append(Annonce(
                    ident=str(p.get("id")),
                    titre=(p.get("name") or "").strip(),
                    url=chemin if chemin.startswith("http") else url.split("/api/")[0] + chemin,
                    lieu="; ".join(lieux),
                    pays=next((x for x in possibles if x in pays), possibles[0] if possibles else ""),
                    publiee_le=publiee,
                    contrat=contrat(p.get("name") or ""),
                ))
            if trop_vieille or len(positions) < PAR_PAGE:
                break
        return annonces

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        racine, domaine = _base(employeur)
        d = quote(domaine)
        if not employeur.options.get("par_pays"):
            annonces = self._pages(
                lambda debut: (f"{racine}/api/pcsx/search?domain={d}&query=&location="
                               f"&start={debut}&sort_by=timestamp"),
                depuis, pays, pages_max * FACTEUR_PAGES, "postedTs", "positions")
        else:
            annonces = []
            for p in pays or [""]:
                lieu = quote(en_anglais(p))
                annonces += self._pages(
                    lambda debut, lieu=lieu: (f"{racine}/api/apply/v2/jobs?domain={d}&start={debut}"
                                              f"&num={PAR_PAGE}&location={lieu}&sort_by=timestamp"),
                    depuis, pays, pages_max, "t_create", "positions")
        vues: dict[str, Annonce] = {}
        for a in annonces:
            if a.titre:
                vues.setdefault(a.ident, a)
        return list(vues.values())

    def completer(self, employeur: Employeur, annonce: Annonce) -> Annonce:
        racine, domaine = _base(employeur)
        if employeur.options.get("par_pays"):
            url = f"{racine}/api/apply/v2/jobs/{annonce.ident}?domain={quote(domaine)}"
        else:
            url = f"{racine}/api/pcsx/position_details?position_id={annonce.ident}&domain={quote(domaine)}&hl=en"
        self.verifier(url)
        r = self.http.get(url, entetes={"Accept": "application/json"})
        corps = r.json_ if isinstance(r.json_, dict) else {}
        d = corps.get("data") or corps
        if not d:
            return annonce
        annonce.description = texte(d.get("jobDescription") or d.get("job_description") or "")
        annonce.url = d.get("publicUrl") or d.get("canonicalPositionUrl") or annonce.url
        annonce.lieu = d.get("location") or annonce.lieu
        annonce.contrat = contrat(annonce.titre, str(d.get("type") or "")) or annonce.contrat
        annonce.complete = True
        return annonce
