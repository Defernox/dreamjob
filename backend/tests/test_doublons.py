"""Un même poste ne sonne qu'une fois — quelle que soit la source, l'agence ou
la passe qui le trouve.

Ce que ces tests protègent :

- **la reconnaissance** : le poste de la banque et sa reprise par France
  Travail sont le même, en français comme en anglais ; deux niveaux, deux
  contrats, deux pays ou deux employeurs ne le sont jamais ;
- **l'alerte unique** : un doublon est marqué signalé sans sonner, ne consomme
  pas le plafond du jour, et ne revient pas dans le résumé du matin ;
- **la réservation** : deux passes concurrentes n'envoient pas la même offre ;
- **l'envoi incertain** : tenu pour parti, jamais renvoyé ; seul un échec
  certain libère l'offre.
"""

from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlmodel import select

from app.models import Profile, ScoreOffre, Utilisateur
from app.models.base import maintenant
from app.services import notification
from app.services.acces import proprietaire
from app.services.doublons import cle_entreprise, cle_intitule, meme_poste

from .conftest import ajouter_offre


def _o(titre, entreprise="Société Générale", lieu="Paris", pays="France", contrat="", source="site", **kw):
    return SimpleNamespace(id=kw.get("id"), hash=kw.get("hash", ""), url=kw.get("url", ""), titre=titre,
                           entreprise=entreprise, lieu=lieu, pays=pays, type_contrat=contrat, source=source)


# --- La reconnaissance ------------------------------------------------------------------


def test_le_poste_de_la_banque_et_sa_reprise_sont_le_meme():
    site = _o("Credit Risk Analyst", "Société Générale")
    reprise = _o("Analyste Risques de Crédit (H/F) - CDI - Paris", "SOCIETE GENERALE SA", lieu="75 - Paris",
                 contrat="CDI", source="france_travail")
    assert meme_poste(site, reprise)


@pytest.mark.parametrize("a, b", [
    (_o("Analyste risques"), _o("Analyste risques senior")),                   # deux niveaux
    (_o("Stage - Analyste risques"), _o("Analyste risques")),                  # stage ou poste
    (_o("Analyste risques", contrat="CDD"), _o("Analyste risques", contrat="CDI")),
    (_o("Analyste risques", pays="France"), _o("Analyste risques", pays="Luxembourg")),
    (_o("Analyste risques", "BNP Paribas"), _o("Analyste risques", "Société Générale")),
    (_o("Analyste risques", "Banque"), _o("Analyste risques", "Banque")),      # « Banque » ne nomme personne
    (_o("Analyste risques", ""), _o("Analyste risques", "")),
    (_o("Analyste risques de marché"), _o("Analyste risques de crédit")),
])
def test_deux_postes_distincts_ne_sont_jamais_confondus(a, b):
    assert not meme_poste(a, b)


def test_le_meme_intitule_dans_deux_agences_est_un_seul_poste():
    """Crystal ouvre « Gestionnaire middle office » à Paris, Montpellier,
    Clermont-Ferrand : une alerte, pas trois."""
    assert meme_poste(_o("Gestionnaire Middle Office - Montpellier H/F", "Groupe Crystal", lieu="Montpellier"),
                      _o("Gestionnaire Middle Office - Clermont-Ferrand H/F", "Groupe Crystal",
                         lieu="Clermont-Ferrand"))


def test_references_genre_et_mot_en_plus():
    assert meme_poste(_o("Risk Analyst REF 2600032A"), _o("Risk Analyst (m/w/d)"))
    # D'une source à l'autre, un mot de plus est une reformulation ; sur un
    # même site, deux intitulés différents sont deux postes.
    assert meme_poste(_o("Analyste risques crédit"), _o("Analyste risques crédit entreprises", source="adzuna"))
    assert not meme_poste(_o("Gestionnaire Middle Office", "Groupe Crystal"),
                          _o("Gestionnaire Middle Office CGPI", "Groupe Crystal"))
    assert not meme_poste(_o("Analyste crédit"), _o("Analyste crédit senior"))
    assert not meme_poste(_o("2026 Summer Analyst"), _o("2027 Summer Analyst")), "deux promotions"


def test_les_cles():
    assert cle_entreprise("SOCIETE GENERALE SA") == cle_entreprise("Société Générale") == {"societe", "generale"}
    assert cle_entreprise("Banque") == frozenset() and cle_entreprise("") == frozenset()
    assert cle_intitule("Analyste Risques de Crédit (H/F) - CDI - Paris", "Paris") \
        == cle_intitule("Credit Risk Analyst", "")


# --- L'alerte unique ------------------------------------------------------------------------


@pytest.fixture
def envois(monkeypatch):
    partis = []

    def faux_post(url, content, headers, timeout):
        partis.append({"url": url, "corps": content.decode("utf-8"),
                       "titre": headers["Title"].decode("utf-8")})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(notification.httpx, "post", faux_post)
    monkeypatch.setenv("NTFY_SUJET", "sujet-de-test")
    return partis


def _offre(session, n, titre, entreprise="Société Générale", score=90, lieu="Paris", source="s",
           utilisateur_id=None, **note):
    o = ajouter_offre(session, utilisateur_id, source=source, source_id=str(n), hash=f"h{n}", titre=titre,
                      entreprise=entreprise, lieu=lieu, pays="France", score=score,
                      date_publication=maintenant() - timedelta(minutes=20), **note)
    session.commit()
    return o


def _note(session, offre, utilisateur_id=None):
    uid = utilisateur_id or proprietaire(session).id
    session.expire_all()
    return session.get(ScoreOffre, (uid, offre.id))


def test_le_meme_poste_venu_de_deux_sources_ne_sonne_qu_une_fois(session, envois):
    depuis = maintenant() - timedelta(hours=1)
    site = _offre(session, 1, "Credit Risk Analyst", score=92, source="employeurs")
    reprise = _offre(session, 2, "Analyste risques de crédit (H/F)", "SOCIETE GENERALE", score=88,
                     source="france_travail")
    assert notification.alerter(session, depuis) == 1
    assert len(envois) == 1 and envois[0]["titre"] == "92 · Credit Risk Analyst", "la mieux notée part"
    jumeau = _note(session, reprise)
    assert jumeau.alertee_le is not None and jumeau.doublon_de == site.id
    assert notification.alertes_du_jour(session, proprietaire(session).id) == 1, "le doublon n'a pas sonné"
    envois.clear()
    assert notification.notifier(session, maintenant() - timedelta(days=1)) == 0, "ni dans le résumé"
    assert envois == []


def test_un_poste_republie_plus_tard_ne_sonne_plus(session, envois):
    ancien = _offre(session, 1, "Analyste risques de crédit", alertee_le=maintenant() - timedelta(days=5))
    nouveau = _offre(session, 2, "Credit Risk Analyst", source="adzuna")
    assert notification.alerter(session, maintenant() - timedelta(hours=1)) == 0
    assert envois == []
    assert _note(session, nouveau).doublon_de == ancien.id


def test_dix_agences_une_alerte_qui_le_dit(session, envois):
    for n, ville in enumerate(["Paris", "Lyon", "Lille"], 1):
        _offre(session, n, f"Gestionnaire Middle Office - {ville} H/F", "Groupe Crystal", score=90 - n, lieu=ville)
    # Le même poste repris par une autre source, lieu écrit autrement : ce n'est
    # pas une agence de plus.
    _offre(session, 9, "Gestionnaire Middle Office H/F", "Groupe Crystal", score=80, lieu="75 - Paris",
           source="adzuna")
    assert notification.alerter(session, maintenant() - timedelta(hours=1)) == 1
    assert "Paris et 2 autres lieux" in envois[0]["corps"]


def test_le_resume_du_matin_ne_compte_qu_un_poste_par_ligne(session, envois):
    _offre(session, 1, "Credit Risk Analyst", score=92)
    _offre(session, 2, "Analyste risques de crédit (H/F)", "SOCIETE GENERALE SA", score=88)
    _offre(session, 3, "Analyste conformité", "BNP Paribas", score=80)
    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 1
    assert envois[0]["titre"] == "2 nouvelles offres vertes"
    assert envois[0]["corps"].splitlines() == ["92 — Credit Risk Analyst · Société Générale",
                                              "80 — Analyste conformité · BNP Paribas"]


def test_deux_comptes_sur_le_meme_telephone_ne_le_font_pas_sonner_deux_fois(session, envois):
    proprietaire(session)
    ami = Utilisateur(email="ami@exemple.fr", mot_de_passe="")
    session.add(ami)
    session.commit()
    session.add(Profile(utilisateur_id=ami.id, ntfy_sujet="sujet-de-test"))
    _offre(session, 1, "Credit Risk Analyst")
    ajouter_offre_ami = _offre(session, 2, "Analyste risques de crédit", utilisateur_id=ami.id)
    assert notification.alerter(session, maintenant() - timedelta(hours=1)) == 1
    assert _note(session, ajouter_offre_ami, ami.id).doublon_de is not None


# --- La réservation, l'envoi incertain ------------------------------------------------------------


def test_une_offre_deja_prise_par_une_autre_passe_n_est_pas_envoyee(session, envois):
    offre = _offre(session, 1, "Credit Risk Analyst")
    paire = [(offre, _note(session, offre))]
    assert notification._reserver(session, paire) is not None
    assert notification._reserver(session, [(offre, _note(session, offre))]) is None, \
        "la seconde passe n'obtient pas la réservation"


def test_un_envoi_incertain_est_tenu_pour_parti(session, monkeypatch):
    monkeypatch.setenv("NTFY_SUJET", "sujet-de-test")
    appels = []

    def lent(url, content, headers, timeout):
        appels.append(url)
        raise httpx.ReadTimeout("réponse trop lente")

    monkeypatch.setattr(notification.httpx, "post", lent)
    offre = _offre(session, 1, "Credit Risk Analyst")
    notification.alerter(session, maintenant() - timedelta(hours=1))
    notification.alerter(session, maintenant() - timedelta(hours=1))
    assert len(appels) == 1, "ntfy a pu la recevoir : on ne la renvoie pas"
    assert _note(session, offre).alertee_le is not None


def test_un_echec_certain_libere_l_offre_pour_la_passe_suivante(session, monkeypatch):
    monkeypatch.setenv("NTFY_SUJET", "sujet-de-test")
    etat = {"panne": True, "appels": 0}

    def post(url, content, headers, timeout):
        etat["appels"] += 1
        if etat["panne"]:
            raise httpx.ConnectError("injoignable")
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(notification.httpx, "post", post)
    offre = _offre(session, 1, "Credit Risk Analyst")
    assert notification.alerter(session, maintenant() - timedelta(hours=1)) == 0
    assert _note(session, offre).alertee_le is None, "rien n'est parti : l'offre reste à signaler"
    etat["panne"] = False
    assert notification.alerter(session, maintenant() - timedelta(hours=1)) == 1
    assert etat["appels"] == 2
    assert session.exec(select(ScoreOffre).where(ScoreOffre.alertee_le.is_(None))).all() == []
