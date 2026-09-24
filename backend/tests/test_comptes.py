"""Plusieurs comptes sur une même instance : chacun ses données, et rien d'autre.

Tout passe par l'API en mode serveur, connecté tour à tour comme le
propriétaire puis comme un ami — c'est le chemin qu'emprunterait une fuite.
Une donnée d'un autre compte répond 404, comme une donnée inexistante : on ne
confirme même pas qu'elle existe.
"""

from datetime import timedelta

import pytest
from sqlmodel import select

from app.config import Source, reglages
from app.connectors import registry
from app.connectors.base import BaseConnector, RawOffer, SearchQuery
from app.models import (
    EMAIL_LOCAL,
    Application,
    DepenseLlm,
    Profile,
    ScanRun,
    ScoreOffre,
    Utilisateur,
)
from app.models.base import maintenant
from app.services.acces import Limiteur, creer_utilisateur, proprietaire
from app.services.scan import Demande, lancer_scan

from .conftest import ajouter_offre

MOT_DE_PASSE = "une phrase assez longue"


@pytest.fixture
def comptes(client, session, monkeypatch):
    """Le propriétaire (premier compte créé) et un ami, en mode serveur."""
    client.base_url = "https://testserver"
    monkeypatch.setenv("DREAMJOB_MODE", "serveur")
    from app.services import acces
    import app.api.acces as route
    monkeypatch.setattr(acces, "limiteur", Limiteur())
    monkeypatch.setattr(route, "limiteur", acces.limiteur)
    moi = creer_utilisateur(session, "moi@exemple.fr", MOT_DE_PASSE)
    ami = creer_utilisateur(session, "ami@exemple.fr", MOT_DE_PASSE)
    return moi.id, ami.id


def en_tant_que(client, email):
    client.cookies.clear()
    reponse = client.post("/api/acces/connexion",
                          json={"email": email, "mot_de_passe": MOT_DE_PASSE})
    assert reponse.status_code == 200


def _offre(session, utilisateur_id, n, **note):
    o = ajouter_offre(session, utilisateur_id, source="t", source_id=str(n), hash=f"h{n}",
                      titre=f"Analyste {n}", entreprise="Banque", pays="France", **note)
    session.commit()
    return o.id


# --- Les comptes eux-mêmes -------------------------------------------------------


def test_le_premier_compte_est_proprietaire_et_les_suivants_ont_un_budget(comptes, session):
    moi, ami = (session.get(Utilisateur, i) for i in comptes)
    assert moi.proprietaire and moi.budget_mensuel_usd is None
    assert not ami.proprietaire
    assert ami.budget_mensuel_usd == reglages().comptes.budget_mensuel_usd


def test_le_premier_compte_reprend_les_donnees_d_une_installation_locale(session):
    """En local, les données appartiennent à un compte « local » sans mot de
    passe. Le premier compte créé sur le serveur le reprend : ses candidatures
    et son profil restent les siens."""
    local = proprietaire(session)
    assert local.email == EMAIL_LOCAL
    session.add(Profile(utilisateur_id=local.id, prenom="Moi"))
    session.commit()

    moi = creer_utilisateur(session, "moi@exemple.fr", MOT_DE_PASSE)
    assert moi.id == local.id and moi.proprietaire
    profil = session.exec(select(Profile).where(Profile.utilisateur_id == moi.id)).one()
    assert profil.prenom == "Moi"
    assert len(session.exec(select(Utilisateur)).all()) == 1


def test_on_ne_se_connecte_pas_au_compte_local(client, session, monkeypatch):
    client.base_url = "https://testserver"
    monkeypatch.setenv("DREAMJOB_MODE", "serveur")
    proprietaire(session)
    reponse = client.post("/api/acces/connexion", json={"email": EMAIL_LOCAL, "mot_de_passe": ""})
    assert reponse.status_code == 401


# --- Profil ------------------------------------------------------------------------


def test_chacun_son_profil(client, comptes):
    en_tant_que(client, "ami@exemple.fr")
    assert client.put("/api/profil", json={"prenom": "Ami"}).status_code == 200
    en_tant_que(client, "moi@exemple.fr")
    assert client.put("/api/profil", json={"prenom": "Moi"}).status_code == 200

    assert client.get("/api/profil").json()["prenom"] == "Moi"
    en_tant_que(client, "ami@exemple.fr")
    assert client.get("/api/profil").json()["prenom"] == "Ami"


# --- Offres : le fil de chacun -------------------------------------------------------


def test_une_offre_hors_de_son_fil_n_existe_pas(client, comptes, session):
    moi, _ = comptes
    offre = _offre(session, moi, 1, score=90.0)

    en_tant_que(client, "ami@exemple.fr")
    assert client.get("/api/offres").json()["total"] == 0
    assert client.get("/api/offres/statistiques").json()["total"] == 0
    for route in (f"/api/offres/{offre}", f"/api/offres/{offre}/correspondance",
                  f"/api/offres/{offre}/documents", f"/api/offres/{offre}/documents/CV.pdf"):
        assert client.get(route).status_code == 404, route
    assert client.post("/api/candidatures", json={"offer_id": offre}).status_code == 404
    assert client.post(f"/api/offres/{offre}/documents").status_code == 404


def test_la_meme_offre_a_une_note_et_un_etat_par_compte(client, comptes, session):
    moi, ami = comptes
    offre = _offre(session, moi, 1, score=90.0)
    session.add(ScoreOffre(utilisateur_id=ami, offer_id=offre, score=30.0))
    session.commit()

    en_tant_que(client, "ami@exemple.fr")
    assert client.get("/api/offres").json()["offres"][0]["score"] == 30.0
    client.get(f"/api/offres/{offre}")                          # l'ami l'ouvre

    en_tant_que(client, "moi@exemple.fr")
    vue = client.get("/api/offres").json()["offres"][0]
    assert vue["score"] == 90.0
    assert vue["vue"] is False, "l'avoir ouverte chez l'ami ne la marque pas lue chez moi"


def test_le_scoring_ne_note_que_son_fil_avec_son_profil(client, comptes, session):
    moi, ami = comptes
    _offre(session, moi, 1)
    session.add(Profile(utilisateur_id=ami, skills=[{"nom": "Analyse financière", "ancree": True}],
                        secteurs=["banque"]))
    session.commit()

    en_tant_que(client, "ami@exemple.fr")
    assert client.post("/api/offres/scorer").json()["scorees"] == 0
    en_tant_que(client, "moi@exemple.fr")
    assert client.post("/api/offres/scorer").status_code == 409, "mon profil est vide"


# --- Candidatures et recherches --------------------------------------------------------


def test_les_candidatures_d_un_autre_sont_invisibles_et_intouchables(client, comptes, session):
    moi, _ = comptes
    offre = _offre(session, moi, 1)
    en_tant_que(client, "moi@exemple.fr")
    candidature = client.post("/api/candidatures", json={"offer_id": offre}).json()["id"]

    en_tant_que(client, "ami@exemple.fr")
    assert client.get("/api/candidatures").json() == []
    assert client.patch(f"/api/candidatures/{candidature}",
                        json={"statut": "Refus"}).status_code == 404
    assert client.delete(f"/api/candidatures/{candidature}").status_code == 404
    session.expire_all()
    assert session.get(Application, candidature).statut == "Envoyée"


def test_deux_comptes_postulent_a_la_meme_annonce(client, comptes, session):
    moi, ami = comptes
    offre = _offre(session, moi, 1)
    session.add(ScoreOffre(utilisateur_id=ami, offer_id=offre))
    session.commit()
    for email in ("moi@exemple.fr", "ami@exemple.fr"):
        en_tant_que(client, email)
        assert client.post("/api/candidatures", json={"offer_id": offre}).status_code == 201
        assert len(client.get("/api/candidatures").json()) == 1


def test_les_recherches_sont_propres_a_chaque_compte(client, comptes):
    corps = {"nom": "CDI Paris", "mots_cles": ["analyste"]}
    en_tant_que(client, "moi@exemple.fr")
    mienne = client.post("/api/recherches", json=corps).json()["id"]

    en_tant_que(client, "ami@exemple.fr")
    assert client.get("/api/recherches").json() == []
    assert client.post("/api/recherches", json=corps).status_code == 201, "même nom, autre compte"
    assert client.patch(f"/api/recherches/{mienne}", json={"active": False}).status_code == 404
    assert client.delete(f"/api/recherches/{mienne}").status_code == 404


def test_un_ami_sans_recherche_ni_titre_n_a_rien_a_chercher(client, comptes):
    """config.yaml porte les mots-clés du propriétaire : l'ami ne doit pas
    hériter de sa recherche."""
    en_tant_que(client, "ami@exemple.fr")
    reponse = client.post("/api/scans")
    assert reponse.status_code == 409
    assert "recherche" in reponse.json()["detail"]


# --- Scans -----------------------------------------------------------------------------


class _Enregistreuse(BaseConnector):
    """Une source qui rend une offre par mot-clé demandé, et note ce qu'on lui a demandé."""

    cle = libelle = "t"
    appels: list = []

    def fetch(self, query):
        type(self).appels.append(list(query.mots_cles))
        return [RawOffer(source=self.cle, source_id=f"{self.cle}-{m}", titre=f"Poste {m}",
                         entreprise="Banque", pays="France",
                         description_brute=f"Une annonce sur {m}.") for m in query.mots_cles]


@pytest.fixture
def sources(monkeypatch):
    class Publique(_Enregistreuse):
        cle = libelle = "publique"
        appels = []

    class Perso(_Enregistreuse):
        cle = libelle = "perso"
        appels = []

    monkeypatch.setattr(registry, "CONNECTEURS", {"publique": Publique, "perso": Perso})
    monkeypatch.setitem(reglages().sources, "perso", Source(actif=True, personnel=True))
    return Publique, Perso


def _fil(session, utilisateur_id):
    from app.models import Offer

    return sorted(o.titre for o, _ in session.exec(
        select(Offer, ScoreOffre).join(ScoreOffre, ScoreOffre.offer_id == Offer.id)
        .where(ScoreOffre.utilisateur_id == utilisateur_id)).all())


def test_chaque_offre_n_entre_que_dans_le_fil_de_qui_l_a_cherchee(comptes, session, sources):
    moi, ami = comptes
    lancer_scan(session, [Demande(moi, SearchQuery(mots_cles=["risques"])),
                          Demande(ami, SearchQuery(mots_cles=["marketing"]))],
                sources=["publique"])
    assert _fil(session, moi) == ["Poste risques"]
    assert _fil(session, ami) == ["Poste marketing"]


def test_une_source_personnelle_ne_travaille_que_pour_le_proprietaire(comptes, session, sources):
    """DogFinance : ses conditions réservent ses annonces à un usage personnel."""
    moi, ami = comptes
    _, perso = sources
    lancer_scan(session, [Demande(moi, SearchQuery(mots_cles=["risques"])),
                          Demande(ami, SearchQuery(mots_cles=["marketing"]))],
                sources=["perso"])
    assert perso.appels == [["risques"]], "la recherche de l'ami n'y est jamais envoyée"
    assert _fil(session, ami) == []

    # Même demandée explicitement par l'ami, la source n'est pas interrogée.
    perso.appels.clear()
    scan = lancer_scan(session, SearchQuery(mots_cles=["x"]), sources=["perso"],
                       utilisateur_id=ami)
    assert perso.appels == [] and scan.sources == []


def test_une_meme_recherche_n_est_jouee_qu_une_fois_pour_deux_comptes(comptes, session, sources):
    moi, ami = comptes
    publique, _ = sources
    lancer_scan(session, [Demande(moi, SearchQuery(mots_cles=["risques"])),
                          Demande(ami, SearchQuery(mots_cles=["risques"]))],
                sources=["publique"])
    assert publique.appels == [["risques"]]
    assert _fil(session, moi) == _fil(session, ami) == ["Poste risques"]


def test_une_offre_deja_en_base_est_nouvelle_pour_qui_la_decouvre(comptes, session, sources):
    moi, ami = comptes
    lancer_scan(session, SearchQuery(mots_cles=["risques"]), sources=["publique"],
                utilisateur_id=moi)
    avant = maintenant()
    scan = lancer_scan(session, SearchQuery(mots_cles=["risques"]), sources=["publique"],
                       utilisateur_id=ami)
    assert scan.nb_nouvelles == 0, "l'annonce est déjà en base"
    note = session.exec(select(ScoreOffre).where(ScoreOffre.utilisateur_id == ami)).one()
    assert note.ajoutee_le >= avant and note.vue is False


def test_l_historique_ne_montre_pas_les_recherches_des_autres(client, comptes, session):
    moi, _ = comptes
    session.add(ScanRun(utilisateur_id=moi, statut="terminé", requete={"mots_cles": ["secret"]}))
    session.add(ScanRun(utilisateur_id=None, statut="terminé", requete={"mots_cles": ["tous"]},
                        declenche_par="planifie"))
    session.commit()

    en_tant_que(client, "ami@exemple.fr")
    historique = client.get("/api/scans").json()
    assert [s["declenche_par"] for s in historique] == ["planifie"]
    assert historique[0]["requete"] == {}, "le scan planifié réunit les mots-clés de tous"


# --- Budget ------------------------------------------------------------------------------


def test_un_ami_au_bout_de_son_budget_ne_genere_plus(client, comptes, session, monkeypatch):
    moi, ami = comptes
    monkeypatch.setattr(reglages().llm, "fournisseur", "anthropic")
    offre = _offre(session, ami, 1)
    session.add(Profile(utilisateur_id=ami, skills=[{"nom": "Analyse", "ancree": True}]))
    budget = session.get(Utilisateur, ami).budget_mensuel_usd
    session.add(DepenseLlm(utilisateur_id=ami, cout_usd=budget + 0.01))
    # Une dépense du mois dernier ne compte plus.
    session.add(DepenseLlm(utilisateur_id=moi, cout_usd=50.0,
                           le=maintenant() - timedelta(days=40)))
    session.commit()

    en_tant_que(client, "ami@exemple.fr")
    reponse = client.post(f"/api/offres/{offre}/documents")
    assert reponse.status_code == 429
    assert "Budget du mois atteint" in reponse.json()["detail"]


def test_ce_que_coute_un_dossier_est_impute_a_son_compte(session, comptes):
    """Même quand la génération échoue en route : les jetons sont facturés."""
    from app.services.budget import consigner, depense_du_mois

    _, ami = comptes

    class Appel:
        consommation = [{"usd": 0.05}, {"usd": 0.02}]

    consigner(session, ami, None, Appel(), None)
    assert depense_du_mois(session, ami) == pytest.approx(0.07)


# --- Documents ---------------------------------------------------------------------------


def test_un_ami_ne_telecharge_jamais_le_dossier_d_un_autre(client, comptes, session,
                                                           tmp_path, monkeypatch):
    import json

    moi, ami = comptes
    monkeypatch.setattr(reglages().chemins, "dossier_candidatures", str(tmp_path))
    offre = _offre(session, moi, 42)
    session.add(ScoreOffre(utilisateur_id=ami, offer_id=offre))
    session.commit()
    d = tmp_path / "2026-09-24-banque-analyste"
    d.mkdir()
    (d / "offre.json").write_text(json.dumps({"source": "t", "source_id": "42"}), encoding="utf-8")
    (d / "CV_Moi.pdf").write_bytes(b"%PDF")

    en_tant_que(client, "moi@exemple.fr")
    assert client.get(f"/api/offres/{offre}/documents").json()["fichiers"][0]["nom"] == "CV_Moi.pdf"
    en_tant_que(client, "ami@exemple.fr")
    assert client.get(f"/api/offres/{offre}/documents").json()["fichiers"] == []
    assert client.get(f"/api/offres/{offre}/documents/CV_Moi.pdf").status_code == 404


def test_les_dossiers_d_un_ami_vivent_a_part(comptes, session):
    from app.api.documents import racine_de

    moi, ami = (session.get(Utilisateur, i) for i in comptes)
    racine = reglages().chemins.candidatures
    assert racine_de(moi) == racine
    assert racine_de(ami) == racine / "comptes" / str(ami.id)


# --- Lettre ---------------------------------------------------------------------------------


def test_les_extraits_de_style_d_un_compte_ne_vont_qu_a_ses_lettres():
    from app.documents.lettre import _message
    from app.models import Offer

    offre = Offer(source="t", source_id="1", titre="Analyste", entreprise="Banque",
                  description_brute="Analyse du risque de crédit.")
    avec = _message(Profile(prenom="A", exemples_style="✓ « ma phrase »"), offre)
    sans = _message(Profile(prenom="B"), offre)
    assert "ma phrase" in avec and "COMMENT J'ÉCRIS" in avec
    assert "COMMENT J'ÉCRIS" not in sans
    assert "Crédit Mutuel" not in sans, "plus aucun extrait écrit en dur dans le code"


def test_l_import_de_cv_d_un_ami_est_aussi_borne_par_son_budget(client, comptes, session,
                                                                monkeypatch):
    _, ami = comptes
    monkeypatch.setattr(reglages().llm, "fournisseur", "anthropic")
    session.add(DepenseLlm(utilisateur_id=ami, cout_usd=100.0))
    session.commit()

    en_tant_que(client, "ami@exemple.fr")
    reponse = client.post("/api/profil/importer",
                          files={"fichier": ("cv.pdf", b"%PDF-1.4", "application/pdf")})
    assert reponse.status_code == 429
