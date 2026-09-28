"""Un scan : interroger les sources actives, dédupliquer, stocker.

Deux règles structurantes :

- **Une source en panne n'interrompt jamais les autres.** L'erreur est consignée
  dans `ScanRun.erreurs` et le scan continue.
- **Aucun appel LLM ici.** Le scan ne fait que collecter ; le scoring est une
  étape séparée, qui travaille sur ce qui est déjà en base.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

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
from ..models import Offer, Recherche, ScanRun, ScoreOffre
from ..models.base import maintenant
from ..models.enums import StatutScan
from .acces import proprietaire
from .dedup import hash_offre

log = logging.getLogger("dreamjob.scan")


@dataclass
class Demande:
    """Une recherche, et le compte pour qui on la joue : c'est dans SON fil que
    les offres retenues entreront."""

    utilisateur_id: int
    requete: SearchQuery


def dernier_scan_abouti(session: Session, utilisateur_id: int | None = None) -> ScanRun | None:
    """Le dernier scan qui a réellement ramené quelque chose.

    Un scan en échec ne compte pas : sinon une panne de source ferait croire que
    la veille est à jour. Un scan partiel, si : les offres des sources valides
    sont bien arrivées.

    Avec `utilisateur_id`, seuls comptent le scan planifié (joué pour tous) et
    ceux que ce compte a lancés : le scan manuel d'un ami ne dit rien de ce qui
    est neuf pour les autres.

    La veille n'en est pas un : elle ne joue que les offres du jour, sur une
    partie des sources. Comptée ici, elle aurait réduit le badge « nouvelles » à
    la dernière demi-heure, et empêché le rattrapage du matin — qui, lui,
    interroge toutes les sources.
    """
    requete = (select(ScanRun)
               .where(ScanRun.statut.in_([StatutScan.TERMINE.value, StatutScan.PARTIEL.value]),
                      ScanRun.declenche_par != "veille"))
    if utilisateur_id is not None:
        requete = requete.where(ScanRun.utilisateur_id.is_(None)
                                | (ScanRun.utilisateur_id == utilisateur_id))
    return session.exec(requete.order_by(desc(ScanRun.started_at)).limit(1)).first()


def requete_par_defaut(reglages: Reglages) -> SearchQuery:
    r = reglages.recherche
    return SearchQuery(
        mots_cles=list(r.mots_cles),
        pays=list(r.pays),
        contrats=list(r.contrats),
        max_offres=r.offres_max_par_source,
    )


def requetes_actives(session: Session, reglages: Reglages,
                     utilisateur_id: int | None = None) -> list[SearchQuery]:
    """Les recherches enregistrées et actives d'un compte, ou une requête de repli.

    Sans recherche définie, on retombe sur le profil : l'application reste
    utilisable avant que l'utilisateur en ait créé une. Un compte sans
    recherche ni titre visé n'a rien à chercher : liste vide.
    """
    proprio_id = proprietaire(session).id
    if utilisateur_id is None:
        utilisateur_id = proprio_id
    recherches = list(session.exec(
        select(Recherche)
        .where(Recherche.active, Recherche.utilisateur_id == utilisateur_id)
        .order_by(Recherche.ordre, Recherche.id)
    ).all())
    repli = requete_depuis_profil(session, reglages, utilisateur_id)
    if not recherches:
        # Le propriétaire retombe sur config.yaml, même sans mots-clés : c'est
        # le comportement d'avant les comptes.
        return [repli] if repli.mots_cles or utilisateur_id == proprio_id else []

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


def demandes_de_tous(session: Session, reglages: Reglages) -> list[Demande]:
    """Ce que le scan planifié joue : les recherches de chaque compte."""
    from ..models import Utilisateur

    proprietaire(session)      # une installation sans compte a quand même le sien
    return [Demande(u.id, q)
            for u in session.exec(select(Utilisateur).order_by(Utilisateur.id)).all()
            for q in requetes_actives(session, reglages, u.id)]


def requete_depuis_profil(session: Session, reglages: Reglages,
                          utilisateur_id: int | None = None) -> SearchQuery:
    """Requête d'un scan automatique.

    Les pays et contrats du **profil** l'emportent sur ceux de `config.yaml` :
    ce que l'utilisateur a coché dans l'interface est son choix explicite, alors
    que `config.yaml` n'est qu'un repli. Sans cela, un scan automatique
    filtrerait sur « France » pendant que le profil accepte quatre pays, et les
    offres étrangères seraient silencieusement jetées.

    Les mots-clés de `config.yaml` sont ceux du propriétaire : un autre compte
    se rabat sur son titre visé, jamais sur la recherche d'un autre.
    """
    from ..models import Profile

    base = requete_par_defaut(reglages)
    proprio = proprietaire(session)
    if utilisateur_id is None:
        utilisateur_id = proprio.id
    profil = session.exec(select(Profile).where(Profile.utilisateur_id == utilisateur_id)).first()
    mots_cles = base.mots_cles if utilisateur_id == proprio.id else (
        [profil.titre_vise] if profil and profil.titre_vise.strip() else [])
    if profil is None:
        return SearchQuery(mots_cles=mots_cles, pays=base.pays, contrats=base.contrats,
                           departement=base.departement,
                           publiee_depuis_jours=base.publiee_depuis_jours,
                           max_offres=base.max_offres)

    return SearchQuery(
        mots_cles=mots_cles,
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
    query: SearchQuery | list[SearchQuery] | list[Demande] | None = None,
    *,
    sources: list[str] | None = None,
    declenche_par: str = "manuel",
    utilisateur_id: int | None = None,
) -> ScanRun:
    """Joue une ou plusieurs requêtes sur les sources actives.

    Plusieurs requêtes produisent **un seul** ScanRun : c'est une recherche du
    point de vue de l'utilisateur, et la déduplication opère sur l'ensemble —
    une offre trouvée par deux recherches n'est stockée qu'une fois.

    Des `SearchQuery` nues sont jouées pour `utilisateur_id` (le propriétaire
    par défaut) ; des `Demande` portent chacune leur compte — c'est le scan
    planifié, joué pour tous.
    """
    reglages = lire_reglages()
    proprio_id = proprietaire(session).id
    pour = utilisateur_id if utilisateur_id is not None else proprio_id
    if query is None:
        brutes: list = [requete_par_defaut(reglages)]
    elif isinstance(query, (SearchQuery, Demande)):
        brutes = [query]
    else:
        brutes = list(query) or [requete_par_defaut(reglages)]
    demandes = [d if isinstance(d, Demande) else Demande(pour, d) for d in brutes]

    cles = sources if sources is not None else cles_actives(reglages)

    scan = ScanRun(
        sources=cles,
        requete={"requetes": [d.requete.en_dict() for d in demandes]} if len(demandes) > 1
        else demandes[0].requete.en_dict(),
        declenche_par=declenche_par,
        utilisateur_id=utilisateur_id,
    )
    session.add(scan)
    session.commit()
    session.refresh(scan)

    erreurs: list[dict] = []
    # Chaque offre ramenée garde les comptes dont une recherche l'a demandée :
    # c'est dans leur fil, et seulement le leur, qu'elle entrera.
    recoltees: list[tuple[RawOffer, set[int]]] = []
    interrogees: list[str] = []

    with client_http(reglages) as http:
        for cle in cles:
            source = reglages.sources.get(cle)
            # Une source personnelle ne travaille que pour le propriétaire :
            # interrogée pour un autre compte, elle lui livrerait ce que ses
            # conditions réservent à un usage personnel.
            pour_elle = [d for d in demandes
                         if not (source and source.personnel) or d.utilisateur_id == proprio_id]
            if not pour_elle:
                log.info("%s : réservée au propriétaire, non interrogée.", cle)
                continue
            interrogees.append(cle)
            try:
                connecteur = construire(cle, http, reglages)
                if getattr(connecteur, "veut_les_connus", False):
                    # Une offre déjà en base n'a pas à voir sa fiche rouverte :
                    # la retrouver dans la liste suffit à la dire en ligne. Son
                    # intitulé vient avec : c'est lui qu'on compare aux
                    # recherches, pas celui, approximatif, tiré de l'adresse.
                    connecteur.connus = dict(session.exec(
                        select(Offer.source_id, Offer.titre).where(Offer.source == cle)).all())
                nombre = 0
                for requete, comptes in _regrouper(pour_elle):
                    for brute in connecteur.fetch(requete):
                        recoltees.append((brute, comptes))
                        nombre += 1
                log.info("%s : %d offres récupérées (%d recherche(s))",
                         cle, nombre, len(pour_elle))
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

    requetes_par_compte: dict[int, list[SearchQuery]] = {}
    for d in demandes:
        requetes_par_compte.setdefault(d.utilisateur_id, []).append(d.requete)
    nouvelles, doublons, rejetees = _stocker(session, recoltees, requetes_par_compte)

    scan.sources = interrogees
    scan.nb_recuperees = len(recoltees)
    scan.nb_nouvelles = nouvelles
    scan.nb_doublons = doublons
    scan.nb_rejetees = rejetees
    scan.nb_appels_llm = 0        # le scan n'appelle jamais le LLM
    scan.erreurs = erreurs
    scan.finished_at = maintenant()
    scan.statut = _statut(interrogees, erreurs)
    session.add(scan)
    session.commit()
    session.refresh(scan)

    log.info("Scan terminé : %d récupérées, %d nouvelles, %d doublons, %d rejetées",
             scan.nb_recuperees, nouvelles, doublons, rejetees)
    return scan


def _regrouper(demandes: list[Demande]) -> list[tuple[SearchQuery, set[int]]]:
    """Une requête identique demandée par deux comptes n'est jouée qu'une fois."""
    groupes: dict[str, tuple[SearchQuery, set[int]]] = {}
    for d in demandes:
        cle = json.dumps(d.requete.en_dict(), sort_keys=True, default=str)
        groupes.setdefault(cle, (d.requete, set()))[1].add(d.utilisateur_id)
    return list(groupes.values())


def _statut(cles: list[str], erreurs: list[dict]) -> str:
    if not cles:
        return StatutScan.ECHEC.value
    en_echec = {e["source"] for e in erreurs}
    if not en_echec:
        return StatutScan.TERMINE.value
    return StatutScan.ECHEC.value if en_echec >= set(cles) else StatutScan.PARTIEL.value


def rattacher(session: Session, utilisateur_id: int, offer_id: int) -> bool:
    """Fait entrer une offre dans le fil d'un compte. Vrai si elle n'y était pas."""
    if session.get(ScoreOffre, (utilisateur_id, offer_id)) is not None:
        return False
    session.add(ScoreOffre(utilisateur_id=utilisateur_id, offer_id=offer_id))
    return True


def _stocker(session: Session, offres: list[tuple[RawOffer, set[int]]],
             requetes_par_compte: dict[int, list[SearchQuery]]) -> tuple[int, int, int]:
    """Insère ce qui est nouveau, et le range dans le fil de chaque compte qui
    l'a cherché. Renvoie (nouvelles, doublons, rejetées)."""
    nouvelles = doublons = rejetees = 0
    # Un doublon peut aussi apparaître *dans* un même lot (deux sources publiant
    # la même annonce, deux recherches qui se recoupent) : on regroupe donc par
    # empreinte, en réunissant les comptes qui l'ont demandée.
    #
    # La déduplication passe AVANT le filtrage : plusieurs recherches ramènent
    # souvent la même annonce, et la compter une fois par recherche gonflerait
    # le nombre de rejets sans rien signifier.
    lot: dict[str, tuple[RawOffer, set[int]]] = {}
    for brute, comptes in offres:
        empreinte = hash_offre(brute)
        if empreinte in lot:
            doublons += 1
            lot[empreinte][1].update(comptes)
            continue
        lot[empreinte] = (brute, set(comptes))

    for empreinte, (brute, comptes) in lot.items():
        # Retenue pour un compte dès qu'UNE de ses recherches l'accepte : une
        # offre V.I.E au Canada ne doit pas être jetée parce que la recherche
        # « CDI Paris » du même compte l'exclut.
        retenue_pour = sorted(u for u in comptes
                              if any(_retenue(brute, q) for q in requetes_par_compte.get(u, [])))
        if not retenue_pour:
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
            offre = deja
        else:
            offre = Offer(
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
            )
            session.add(offre)
            session.flush()          # l'identifiant, pour la rattacher aux comptes
            nouvelles += 1

        for utilisateur_id in retenue_pour:
            rattacher(session, utilisateur_id, offre.id)

    session.commit()
    return nouvelles, doublons, rejetees
