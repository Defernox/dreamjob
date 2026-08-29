"""Les améliorations issues de l'audit : expiration des offres, relances,
synonymes métier, exigences linguistiques, sauvegarde de la base."""

from datetime import timedelta
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.config import PoidsScoring
from app.models import Application, Offer, Profile
from app.models.base import maintenant
from app.scoring.extraction import extraire
from app.scoring.langue import langues_exigees
from app.scoring.score import calculer, score_langue
from app.scoring.synonymes import equivalents, present
from app.scoring.texte import normaliser
from app.services.sauvegarde import sauvegarder


def fichier_de(engine) -> Path:
    return Path(engine.url.database)


# --- Offres retirées du site -------------------------------------------------


def test_une_offre_revue_recemment_n_est_pas_expiree(client, engine):
    with Session(engine) as s:
        s.add(Offer(source="t", source_id="1", hash="h1", titre="Analyste",
                    derniere_vue_le=maintenant()))
        s.commit()
    assert client.get("/api/offres").json()["offres"][0]["expiree"] is False
    assert client.get("/api/offres/statistiques").json()["expirees"] == 0


def test_une_offre_plus_revue_depuis_longtemps_est_signalee(client, engine):
    """Une annonce retirée du site cesse d'être revue par les scans. La
    signaler évite de préparer un dossier pour rien."""
    with Session(engine) as s:
        s.add(Offer(source="t", source_id="1", hash="h1", titre="Analyste",
                    derniere_vue_le=maintenant() - timedelta(days=40)))
        s.commit()
    assert client.get("/api/offres").json()["offres"][0]["expiree"] is True
    assert client.get("/api/offres/statistiques").json()["expirees"] == 1


def test_on_peut_isoler_ou_masquer_les_offres_expirees(client, engine):
    with Session(engine) as s:
        s.add(Offer(source="t", source_id="1", hash="h1", titre="Récente",
                    derniere_vue_le=maintenant()))
        s.add(Offer(source="t", source_id="2", hash="h2", titre="Ancienne",
                    derniere_vue_le=maintenant() - timedelta(days=40)))
        s.commit()
    assert client.get("/api/offres?expirees=false").json()["total"] == 1
    assert client.get("/api/offres?expirees=true").json()["total"] == 1
    assert client.get("/api/offres").json()["total"] == 2


def test_revoir_une_offre_rafraichit_sa_date(session):
    """Un doublon n'est pas du bruit : c'est la preuve que l'annonce tient."""
    from app.connectors.base import RawOffer, SearchQuery
    from app.services.scan import _stocker

    brute = RawOffer(source="t", source_id="1", titre="Analyste", entreprise="X",
                     description_brute="Une description suffisamment longue.")
    _stocker(session, [brute], [SearchQuery()])

    offre = session.exec(select(Offer)).one()
    offre.derniere_vue_le = maintenant() - timedelta(days=40)
    session.add(offre)
    session.commit()

    _stocker(session, [brute], [SearchQuery()])
    session.expire_all()
    revue = session.exec(select(Offer)).one().derniere_vue_le
    assert revue > maintenant() - timedelta(minutes=1)


# --- Relances ----------------------------------------------------------------


def _candidature(client, engine, *, jours: int, statut: str = "Envoyée") -> dict:
    with Session(engine) as s:
        offre = Offer(source="t", source_id="1", hash="h1", titre="Analyste")
        s.add(offre)
        s.commit()
        s.refresh(offre)
        s.add(Application(offer_id=offre.id, statut=statut,
                          date_candidature=maintenant() - timedelta(days=jours)))
        s.commit()
    return client.get("/api/candidatures").json()[0]


def test_une_candidature_recente_n_appelle_pas_de_relance(client, engine):
    candidature = _candidature(client, engine, jours=3)
    assert candidature["jours_depuis"] == 3
    assert candidature["relance_conseillee"] is False


def test_une_candidature_sans_nouvelle_est_signalee(client, engine):
    assert _candidature(client, engine, jours=30)["relance_conseillee"] is True


@pytest.mark.parametrize("statut", ["Entretien", "Refus", "Acceptée", "Relancée"])
def test_seul_le_statut_envoyee_appelle_une_relance(client, engine, statut):
    """Relancer un refus n'a aucun sens."""
    candidature = _candidature(client, engine, jours=60, statut=statut)
    assert candidature["relance_conseillee"] is False


# --- Synonymes métier --------------------------------------------------------


@pytest.mark.parametrize("terme", ["risques", "crédit", "trésorerie", "analyse"])
def test_un_terme_francais_est_reconnu_dans_une_offre_anglaise(terme):
    """Sans cela, « risques de crédit » ne rencontre jamais « credit risk »."""
    anglaise = {"credit", "risk", "analyst", "counterparty", "treasury"}
    assert present(normaliser(terme), anglaise)


def test_un_terme_hors_du_domaine_n_est_pas_invente():
    assert not present("boulangerie", {"credit", "risk"})
    assert equivalents("boulangerie") == frozenset({"boulangerie"})


def test_les_synonymes_relevent_le_score_d_une_offre_anglaise():
    profil = Profile(skills=[{"nom": "Gestion des risques de crédit", "ancree": True}],
                     langues=[{"code": "en", "niveau": "courant"}])
    offre = Offer(source="t", source_id="1", titre="Credit Risk Analyst",
                  description_brute="You will monitor credit risk exposures of our "
                                    "counterparties and report to the management team.")
    resultat = calculer(profil, offre, extraire(offre), PoidsScoring())
    assert resultat.detail["competences"] > 50
    assert "Gestion des risques de crédit" in resultat.ancrees_trouvees


# --- Exigences linguistiques -------------------------------------------------


@pytest.mark.parametrize("texte, attendu", [
    ("Anglais courant exigé pour ce poste basé à Paris chez nous.", ["en"]),
    ("La maîtrise de l'allemand est indispensable au quotidien ici.", ["de"]),
    ("Fluent English required for this position in our team today.", ["en"]),
    ("Notre équipe parle anglais et espagnol au quotidien dans nos bureaux.", []),
])
def test_seules_les_vraies_exigences_sont_relevees(texte, attendu):
    """Mieux vaut manquer une exigence que d'écarter une offre à tort."""
    assert langues_exigees(texte) == attendu


def test_une_langue_exigee_et_non_maitrisee_fait_chuter_le_critere():
    """Une offre en français réclamant l'allemand était jugée parfaitement
    accessible : seule la langue de rédaction comptait."""
    profil = Profile(langues=[{"code": "fr", "niveau": "natif"}])
    offre = Offer(source="t", source_id="1",
                  description_brute="Poste d'analyste à Paris. La maîtrise de "
                                    "l'allemand est indispensable pour ce poste.")
    assert score_langue(profil, extraire(offre)) == 0.0


def test_une_langue_exigee_et_maitrisee_ne_penalise_pas():
    profil = Profile(langues=[{"code": "fr", "niveau": "natif"},
                              {"code": "en", "niveau": "courant"}])
    offre = Offer(source="t", source_id="1",
                  description_brute="Poste d'analyste à Paris. Anglais courant "
                                    "exigé pour les échanges avec les filiales.")
    assert score_langue(profil, extraire(offre)) == 100.0


# --- Sauvegarde de la base ---------------------------------------------------


def test_la_sauvegarde_copie_reellement_les_donnees(engine, tmp_path):
    import sqlite3

    with Session(engine) as s:
        s.add(Offer(source="t", source_id="1", hash="h1", titre="Analyste"))
        s.commit()

    copie = sauvegarder(fichier_de(engine), tmp_path / "sauvegardes")
    assert copie is not None and copie.exists()

    connexion = sqlite3.connect(copie)
    try:
        assert connexion.execute("SELECT COUNT(*) FROM offer").fetchone()[0] == 1
    finally:
        connexion.close()


def test_seules_les_dernieres_sauvegardes_sont_conservees(engine, tmp_path):
    dossier = tmp_path / "sauvegardes"
    dossier.mkdir()
    for jour in range(1, 13):
        (dossier / f"dreamjob-2026-01-{jour:02d}.db").write_bytes(b"")

    sauvegarder(fichier_de(engine), dossier, a_conserver=7)
    assert len(list(dossier.glob("dreamjob-*.db"))) == 7


def test_une_base_absente_ne_fait_pas_echouer_le_demarrage(tmp_path):
    """Une sauvegarde qui échoue ne doit jamais empêcher l'application de démarrer."""
    assert sauvegarder(tmp_path / "fantome.db", tmp_path / "sauvegardes") is None
