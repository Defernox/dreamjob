"""Un scan : interroger les sources actives, dédupliquer, stocker.

Deux règles structurantes :

- **Une source en panne n'interrompt jamais les autres.** L'erreur est consignée
  dans `ScanRun.erreurs` et le scan continue.
- **Aucun appel LLM ici.** Le scan ne fait que collecter ; le scoring est une
  étape séparée, qui travaille sur ce qui est déjà en base.
"""

from __future__ import annotations

import logging

from sqlmodel import Session, desc, select

from ..config import Reglages
from ..config import reglages as lire_reglages
from ..connectors.base import (
    ConnecteurNonConfigure,
    ErreurConnecteur,
    RawOffer,
    SearchQuery,
)
from ..connectors.registry import cles_actives, client_http, construire
from ..models import Offer, ScanRun
from ..models.base import maintenant
from ..models.enums import StatutScan
from .dedup import hash_offre

log = logging.getLogger("dreamjob.scan")


def dernier_scan_abouti(session: Session) -> ScanRun | None:
    """Le dernier scan qui a réellement ramené quelque chose.

    Un scan en échec ne compte pas : sinon une panne de source ferait croire que
    la veille est à jour. Un scan partiel, si : les offres des sources valides
    sont bien arrivées.
    """
    return session.exec(
        select(ScanRun)
        .where(ScanRun.statut.in_([StatutScan.TERMINE.value, StatutScan.PARTIEL.value]))
        .order_by(desc(ScanRun.started_at))
        .limit(1)
    ).first()


def requete_par_defaut(reglages: Reglages) -> SearchQuery:
    r = reglages.recherche
    return SearchQuery(
        mots_cles=list(r.mots_cles),
        pays=list(r.pays),
        contrats=list(r.contrats),
        max_offres=r.offres_max_par_source,
    )


def requete_depuis_profil(session: Session, reglages: Reglages) -> SearchQuery:
    """Requête d'un scan automatique.

    Les pays et contrats du **profil** l'emportent sur ceux de `config.yaml` :
    ce que l'utilisateur a coché dans l'interface est son choix explicite, alors
    que `config.yaml` n'est qu'un repli. Sans cela, un scan automatique
    filtrerait sur « France » pendant que le profil accepte quatre pays, et les
    offres étrangères seraient silencieusement jetées.
    """
    from ..models import Profile

    base = requete_par_defaut(reglages)
    profil = session.exec(select(Profile).order_by(Profile.id)).first()
    if profil is None:
        return base

    return SearchQuery(
        mots_cles=base.mots_cles,
        pays=list(profil.pays_acceptes) or base.pays,
        contrats=list(profil.contrats_acceptes) or base.contrats,
        departement=base.departement,
        publiee_depuis_jours=base.publiee_depuis_jours,
        max_offres=base.max_offres,
    )


def _retenue(offre: RawOffer, query: SearchQuery) -> bool:
    """Filtres durs, appliqués avant stockage : inutile de garder ce qu'on n'ira
    jamais lire. Le tri fin, lui, est du ressort du scoring."""
    if query.pays and offre.pays and offre.pays not in query.pays:
        return False
    if query.contrats and offre.type_contrat and offre.type_contrat not in query.contrats:
        return False
    return True


def lancer_scan(
    session: Session,
    query: SearchQuery | None = None,
    *,
    sources: list[str] | None = None,
    declenche_par: str = "manuel",
) -> ScanRun:
    reglages = lire_reglages()
    query = query or requete_par_defaut(reglages)
    cles = sources if sources is not None else cles_actives(reglages)

    scan = ScanRun(sources=cles, requete=query.en_dict(), declenche_par=declenche_par)
    session.add(scan)
    session.commit()
    session.refresh(scan)

    erreurs: list[dict] = []
    recoltees: list[RawOffer] = []

    with client_http(reglages) as http:
        for cle in cles:
            try:
                offres = construire(cle, http, reglages).fetch(query)
                recoltees.extend(offres)
                log.info("%s : %d offres récupérées", cle, len(offres))
            except ConnecteurNonConfigure as e:
                # Pas une panne : la source n'est simplement pas branchée.
                erreurs.append({"source": cle, "type": "non_configure", "erreur": str(e)})
                log.warning("%s : non configuré — %s", cle, e)
            except ErreurConnecteur as e:
                erreurs.append({"source": cle, "type": "panne", "erreur": str(e)})
                log.error("%s : en panne — %s", cle, e)
            except Exception as e:  # noqa: BLE001 — un bug de connecteur ne tue pas le scan
                erreurs.append({"source": cle, "type": "inattendu",
                                "erreur": f"{type(e).__name__}: {e}"})
                log.exception("%s : erreur inattendue", cle)

    nouvelles, doublons, rejetees = _stocker(session, recoltees, query)

    scan.nb_recuperees = len(recoltees)
    scan.nb_nouvelles = nouvelles
    scan.nb_doublons = doublons
    scan.nb_rejetees = rejetees
    scan.nb_appels_llm = 0        # le scan n'appelle jamais le LLM
    scan.erreurs = erreurs
    scan.finished_at = maintenant()
    scan.statut = _statut(cles, erreurs)
    session.add(scan)
    session.commit()
    session.refresh(scan)

    log.info("Scan terminé : %d récupérées, %d nouvelles, %d doublons, %d rejetées",
             scan.nb_recuperees, nouvelles, doublons, rejetees)
    return scan


def _statut(cles: list[str], erreurs: list[dict]) -> str:
    if not cles:
        return StatutScan.ECHEC.value
    en_echec = {e["source"] for e in erreurs}
    if not en_echec:
        return StatutScan.TERMINE.value
    return StatutScan.ECHEC.value if en_echec >= set(cles) else StatutScan.PARTIEL.value


def _stocker(session: Session, offres: list[RawOffer], query: SearchQuery) -> tuple[int, int, int]:
    """Insère ce qui est nouveau. Renvoie (nouvelles, doublons, rejetées)."""
    nouvelles = doublons = rejetees = 0
    # Un doublon peut aussi apparaître *dans* un même lot (deux sources publiant
    # la même annonce) : on suit donc les empreintes vues pendant ce scan.
    vus: set[str] = set()

    for brute in offres:
        if not _retenue(brute, query):
            rejetees += 1
            continue

        empreinte = hash_offre(brute)
        if empreinte in vus:
            doublons += 1
            continue
        vus.add(empreinte)

        deja = session.exec(
            select(Offer).where(
                (Offer.hash == empreinte)
                | ((Offer.source == brute.source) & (Offer.source_id == brute.source_id))
            )
        ).first()
        if deja is not None:
            doublons += 1
            continue

        session.add(Offer(
            source=brute.source,
            source_id=brute.source_id,
            url=brute.url,
            titre=brute.titre,
            entreprise=brute.entreprise,
            lieu=brute.lieu,
            pays=brute.pays,
            type_contrat=brute.type_contrat,
            date_publication=brute.date_publication,
            description_brute=brute.description_brute,
            hash=empreinte,
            raw=brute.raw,
            vue=False,
        ))
        nouvelles += 1

    session.commit()
    return nouvelles, doublons, rejetees
