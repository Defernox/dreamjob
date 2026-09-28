"""Talentsoft (Cegid) : Crédit Agricole CIB, CACEIS, Amundi, LCL, Indosuez,
Candriam, AMF, CNP, Arkéa…

Les sites Talentsoft sont des pages serveur, sans interface JSON, mais ils
publient ce qu'il faut. Vérifié le 2026-09-28 sur jobs.ca-cib.com :

- **un flux RSS officiel** (`/handlers/offerRss.ashx`), les vingt offres les plus
  récentes avec leur date à la seconde, leur contrat et leur ville : c'est lui
  que lit la veille, une requête par employeur ;
- **la liste** (`/offre-de-emploi/liste-offres.aspx?page=N`), cent offres par
  page, de la plus récente à la plus ancienne, avec contrat, pays et ville —
  mais sans date. Le scan du matin la parcourt, et y reporte les dates du flux ;
- **la fiche**, en champs à identifiant stable (`fldjobdescription_contract`,
  `fldlocation_location_geographicalareacollection`…), niveau d'études et
  expérience exigée compris ;
- `robots.txt` vide.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape

from ...models.base import maintenant
from .commun import Annonce, contrat, texte
from .logiciel import Logiciel
from .pays import depuis_lieu, depuis_nom
from .registre import Employeur

# Au-delà, la liste est parcourue : le flux ne garde que vingt offres.
JOURS_DU_FLUX = 3
LISTE = "/offre-de-emploi/liste-offres.aspx"
# Deux gabarits selon le site : des « cartes » (CA CIB, Arkéa) ou une « liste »
# (CACEIS, Amundi). Les champs sous l'intitulé sont choisis par chaque site —
# contrat, pays, ville, date ou entité : on les reconnaît à leur forme.
_CARTE = re.compile(
    r'<a\s+class="ts-offer-(?:card|list-item)__title-link[^"]*"\s+href="([^"]+_(\d+)\.aspx)"[^>]*>(.*?)</a>'
    r'.*?<ul class="ts-offer-(?:card-content__list|list-item__description)[^"]*">(.*?)</ul>', re.S)
_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_ITEM = re.compile(r"<li[^>]*>(.*?)</li>", re.S)
_CHAMP = r'id="{}"[^>]*>(.*?)</(?:p|div)>'
_REFERENCE = re.compile(r"^\s*\d{4}-\d+\s*-\s*")
_ID_OFFRE = re.compile(r"idOffre=(\d+)|_(\d+)\.aspx", re.I)
_MAJ = re.compile(r"Date de mise à jour\s*</h3>\s*(\d{2}/\d{2}/\d{4})|Update date\s*</h3>\s*(\d{2}/\d{2}/\d{4})")


def _propre(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _champ(html: str, ident: str) -> str:
    m = re.search(_CHAMP.format(re.escape(ident)), html, re.S)
    return _propre(m.group(1)) if m else ""


def _pays_de(zones: str) -> str:
    """« Europe, France, Ile-de-France, 92 - Hauts-De-Seine » → France."""
    for zone in zones.split(","):
        if pays := depuis_nom(zone):
            return pays
    return ""


class Talentsoft(Logiciel):
    cle = "talentsoft"

    @staticmethod
    def _base(employeur: Employeur) -> str:
        return re.match(r"https?://[^/]+", employeur.adresse).group(0)

    @staticmethod
    def _lcid(employeur: Employeur) -> int:
        return int(employeur.options.get("lcid", 1036))

    def _flux(self, employeur: Employeur) -> list[Annonce]:
        base = self._base(employeur)
        url = f"{base}/handlers/offerRss.ashx?LCID={self._lcid(employeur)}"
        self.verifier(url)
        r = self.http.get(url, utiliser_cache=False)
        try:
            racine = ET.fromstring(r.texte.encode("utf-8") if isinstance(r.texte, str) else r.texte)
        except ET.ParseError:
            return []
        annonces = []
        for item in racine.iter("item"):
            lien = (item.findtext("link") or "").strip()
            m = _ID_OFFRE.search(lien)
            if not m:
                continue
            categories = [c.text or "" for c in item.findall("category")]
            try:
                publiee = parsedate_to_datetime(item.findtext("pubDate") or "").replace(tzinfo=None)
            except (TypeError, ValueError):
                publiee = None
            lieu = categories[-1] if len(categories) >= 3 else ""
            annonces.append(Annonce(
                ident=m.group(1) or m.group(2),
                titre=_REFERENCE.sub("", item.findtext("title") or "").strip(),
                url=lien,
                lieu=lieu,
                pays=depuis_lieu(lieu),
                publiee_le=publiee,
                contrat=contrat(*categories[1:2], item.findtext("title") or ""),
            ))
        return annonces

    def _liste(self, employeur: Employeur, pages_max: int) -> list[Annonce]:
        base = self._base(employeur)
        annonces: list[Annonce] = []
        vus: set[str] = set()
        for page in range(1, pages_max + 1):
            url = f"{base}{employeur.options.get('liste', LISTE)}?page={page}&LCID={self._lcid(employeur)}"
            self.verifier(url)
            html = self.http.get(url, utiliser_cache=False).texte
            nouvelles = 0
            for chemin, ident, titre, details in _CARTE.findall(html):
                if ident in vus:
                    continue
                vus.add(ident)
                nouvelles += 1
                publiee, pays, lieu, contrat_ = None, "", "", ""
                for champ in (_propre(x) for x in _ITEM.findall(details)):
                    if m := _DATE.match(champ):
                        publiee = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                    elif not contrat_ and (c := contrat(champ)):
                        contrat_ = c
                    elif not pays and (p := depuis_nom(champ)):
                        pays = p
                    else:
                        lieu = champ
                annonces.append(Annonce(
                    ident=ident, titre=_propre(titre), url=f"{base}{chemin}",
                    lieu=lieu, pays=pays or depuis_lieu(lieu), publiee_le=publiee,
                    contrat=contrat_ or contrat(_propre(titre)),
                ))
            # Une page au-delà de la dernière rend la première, ou rien.
            if nouvelles == 0:
                break
        return annonces

    def annonces(self, employeur: Employeur, pays: list[str], depuis: datetime,
                 pages_max: int) -> list[Annonce]:
        flux = self._flux(employeur)
        if (maintenant() - depuis).days <= JOURS_DU_FLUX:
            retenues = [a for a in flux if a.publiee_le is None or a.publiee_le >= depuis]
        else:
            dates = {a.ident: a.publiee_le for a in flux}
            retenues = self._liste(employeur, pages_max)
            for a in retenues:
                a.publiee_le = dates.get(a.ident) or a.publiee_le
        return [a for a in retenues if not (pays and a.pays and a.pays not in pays)]

    def completer(self, employeur: Employeur, annonce: Annonce) -> Annonce:
        self.verifier(annonce.url)
        html = self.http.get(annonce.url).texte
        debut = html.find('class="JobDescription"')
        if debut < 0:
            debut = html.find('id="contenu-ficheoffre"')
        if debut < 0:
            return annonce
        fin = html.find("Postuler", debut)
        corps = html[debut:fin if fin > 0 else None]
        annonce.description = texte(corps[corps.find(">") + 1:])
        titre = _champ(html, "fldjobdescription_jobtitle")
        annonce.titre = titre or annonce.titre
        annonce.contrat = contrat(_champ(html, "fldjobdescription_contract"), annonce.titre) or annonce.contrat
        zones = _champ(html, "fldlocation_location_geographicalareacollection")
        ville = _champ(html, "fldlocation_joblocation")
        annonce.pays = _pays_de(zones) or depuis_lieu(ville) or annonce.pays
        annonce.lieu = ville or annonce.lieu
        if annonce.publiee_le is None and (m := _MAJ.search(html)):
            try:
                annonce.publiee_le = datetime.strptime(m.group(1) or m.group(2), "%d/%m/%Y")
            except ValueError:
                pass
        annonce.complete = True
        return annonce
