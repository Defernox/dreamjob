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
from ..models import Offer, Recherche, ScanRun
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


def requetes_actives(session: Session, reglages: Reglages) -> list[SearchQuery]:
    """Les recherches enregistrées et actives, ou une requête unique par défaut.

    Sans recherche définie, on retombe sur le profil : l'application reste
    utilisable avant que l'utilisateur en ait créé une.
    """
    recherches = list(session.exec(
        select(Recherche).where(Recherche.active).order_by(Recherche.ordre, Recherche.id)
    ).all())
    if not recherches:
        return [requete_depuis_profil(session, reglages)]

    repli = requete_depuis_profil(session, reglages)
    return [
        SearchQuery(
            mots_cles=list(r.mots_cles),
            # Vides = les préférences du profil : une recherche n'a pas à
            # répéter les pays acceptés si elle ne les restreint pas.
            pays=list(r.pays) or repli.pays,
            contrats=list(r.contrats) or repli.contrats,
            departement=r.departement,
            publiee_depuis_jours=r.publiee_depuis_jours,
            max_offres=r.max_offres,
        )
        for r in recherches
    ]


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
    query: SearchQuery | list[SearchQuery] | None = None,
    *,
    sources: list[str] | None = None,
    declenche_par: str = "manuel",
) -> ScanRun:
    """Joue une ou plusieurs requêtes sur les sources actives.

    Plusieurs requêtes produisent **un seul** ScanRun : c'est une recherche du
    point de vue de l'utilisateur, et la déduplication opère sur l'ensemble —
    une offre trouvée par deux recherches n'est stockée qu'une fois.
    """
    reglages = lire_reglages()
    if query is None:
        requetes = [requete_par_defaut(reglages)]
    elif isinstance(query, SearchQuery):
        requetes = [query]
    else:
        requetes = list(query) or [requete_par_defaut(reglages)]

    cles = sources if sources is not None else cles_actives(reglages)

    scan = ScanRun(
        sources=cles,
        requete={"requetes": [r.en_dict() for r in requetes]} if len(requetes) > 1
        else requetes[0].en_dict(),
        declenche_par=declenche_par,
    )
    session.add(scan)
    session.commit()
    session.refresh(scan)

    erreurs: list[dict] = []
    recoltees: list[RawOffer] = []

    with client_http(reglages) as http:
        for cle in cles:
            try:
                connecteur = construire(cle, http, reglages)
                offres = []
                for requete in requetes:
                    offres.extend(connecteur.fetch(requete))
                recoltees.extend(offres)
                log.info("%s : %d offres récupérées (%d recherche(s))",
                         cle, len(offres), len(requetes))
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

    nouvelles, doublons, rejetees = _stocker(session, recoltees, requetes)

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


def _stocker(session: Session, offres: list[RawOffer],
             requetes: list[SearchQuery]) -> tuple[int, int, int]:
    """Insère ce qui est nouveau. Renvoie (nouvelles, doublons, rejetées)."""
    nouvelles = doublons = rejetees = 0
    # Un doublon peut aussi apparaître *dans* un même lot (deux sources publiant
    # la même annonce) : on suit donc les empreintes vues pendant ce scan.
    vus: set[str] = set()

    for brute in offres:
        # La déduplication passe AVANT le filtrage : plusieurs recherches
        # ramènent souvent la même annonce, et la compter une fois par
        # recherche gonflerait le nombre de rejets sans rien signifier.
        empreinte = hash_offre(brute)
        if empreinte in vus:
            doublons += 1
            continue
        vus.add(empreinte)

        # Retenue dès qu'UNE recherche l'accepte : une offre V.I.E au Canada
        # ne doit pas être jetée parce que la recherche « CDI Paris » l'exclut.
        if not any(_retenue(brute, requete) for requete in requetes):
            rejetees += 1
            continue

        deja = session.exec(
            select(Offer).where(
                (Offer.hash == empreinte)
                | ((Offer.source == brute.source) & (Offer.source_id == brute.source_id))
            )
        ).first()
        if deja is not None:
            # Retrouver une annonce, c'est constater qu'elle est toujours en
            # ligne : c'est cette date qui permettra de repérer celles qui ont
            # disparu du site.
            deja.derniere_vue_le = maintenant()
            session.add(deja)
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
