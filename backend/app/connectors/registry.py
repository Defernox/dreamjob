"""Inventaire des connecteurs.

Une source vit à deux endroits, et seulement deux : sa classe ici, son entrée
dans `config.yaml`. Une source absente de `config.yaml` n'est jamais interrogée,
même si sa classe existe.
"""

from __future__ import annotations

import logging

from ..config import Reglages
from .base import BaseConnector
from .adzuna import AdzunaConnector
from .civiweb import CiviwebConnector
from .france_travail import FranceTravailConnector
from .http import ClientHttp

log = logging.getLogger("dreamjob.connecteurs")

CONNECTEURS: dict[str, type[BaseConnector]] = {
    FranceTravailConnector.cle: FranceTravailConnector,
    CiviwebConnector.cle: CiviwebConnector,
    AdzunaConnector.cle: AdzunaConnector,
}


def cles_actives(reglages: Reglages) -> list[str]:
    """Sources actives dans config.yaml **et** effectivement implémentées."""
    actives = []
    for cle, source in reglages.sources.items():
        if not source.actif:
            continue
        if cle not in CONNECTEURS:
            log.warning("Source « %s » active dans config.yaml mais pas encore implémentée.", cle)
            continue
        actives.append(cle)
    return actives


def construire(cle: str, http: ClientHttp, reglages: Reglages) -> BaseConnector:
    if cle not in CONNECTEURS:
        raise KeyError(f"Connecteur inconnu : {cle}")
    return CONNECTEURS[cle](http, reglages)


def client_http(reglages: Reglages) -> ClientHttp:
    """Le client partagé : limitation de débit et cache communs à toutes les sources."""
    r = reglages.http
    return ClientHttp(
        user_agent=reglages.user_agent,
        requetes_par_seconde=r.requetes_par_seconde,
        timeout=r.timeout_secondes,
        tentatives_max=r.tentatives_max,
        dossier_cache=reglages.chemins.dossier_cache / "http",
        cache_ttl_heures=r.cache_ttl_heures,
    )
