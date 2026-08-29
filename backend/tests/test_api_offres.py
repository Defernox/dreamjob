"""L'API des offres : filtres, compteurs de facettes, tri, scoring."""

import pytest
from sqlmodel import Session, select

from app.models import Application, Offer, Profile
from app.models.base import maintenant


@pytest.fixture
def base_remplie(engine):
    """Six offres variées, sans score : le scoring est déclenché par les tests."""
    lignes = [
        dict(source="france_travail", source_id="1", hash="h1", titre="Analyste risques de crédit",
             entreprise="Banque A", pays="France", type_contrat="CDI", score=88.0,
             description_brute="Vous évaluez la solvabilité des contreparties et suivez les encours."),
        dict(source="france_travail", source_id="2", hash="h2", titre="Assistant trésorerie",
             entreprise="Groupe B", pays="France", type_contrat="Alternance", score=61.0,
             description_brute="Vous assistez le trésorier dans le suivi des flux."),
        dict(source="adzuna", source_id="3", hash="h3", titre="Credit Risk Analyst",
             entreprise="Global Bank", pays="Luxembourg", type_contrat="CDI", score=72.0,
             description_brute="You will assess the solvency of our corporate clients."),
        dict(source="adzuna", source_id="4", hash="h4", titre="Boulanger",
             entreprise="Fournil", pays="France", type_contrat="CDI", score=25.0,
             description_brute="Vous confectionnez les pains chaque matin."),
        dict(source="civiweb", source_id="5", hash="h5", titre="V.I.E Analyste financier",
             entreprise="Corp C", pays="Canada", type_contrat="V.I.E", score=55.0,
             description_brute="Analyse financière des filiales du groupe."),
        dict(source="civiweb", source_id="6", hash="h6", titre="Stage contrôle de gestion",
             entreprise="Corp D", pays="France", type_contrat="Stage", score=None,
             description_brute="Stage de six mois en contrôle de gestion."),
    ]
    with Session(engine) as s:
        for i, ligne in enumerate(lignes):
            s.add(Offer(date_publication=maintenant(), **ligne))
        s.commit()
    return engine


# --- Liste et tri ----------------------------------------------------------


def test_liste_complete(client, base_remplie):
    page = client.get("/api/offres").json()
    assert page["total"] == 6
    assert len(page["offres"]) == 6


def test_tri_par_pertinence_place_les_meilleurs_scores_devant(client, base_remplie):
    scores = [o["score"] for o in client.get("/api/offres?tri=pertinence").json()["offres"]]
    assert scores[:3] == [88.0, 72.0, 61.0]
    assert scores[-1] is None, "les offres non scorées passent en dernier"


def test_tri_par_anciennete(client, base_remplie):
    page = client.get("/api/offres?tri=anciennes").json()
    assert page["total"] == 6


def test_tri_inconnu_refuse(client, base_remplie):
    reponse = client.get("/api/offres?tri=alphabetique")
    assert reponse.status_code == 400
    assert "pertinence" in reponse.json()["detail"]


# --- Filtres ---------------------------------------------------------------


def test_filtre_par_contrat(client, base_remplie):
    page = client.get("/api/offres?contrats=CDI").json()
    assert page["total"] == 3
    assert {o["type_contrat"] for o in page["offres"]} == {"CDI"}


def test_filtres_cumules(client, base_remplie):
    page = client.get("/api/offres?contrats=CDI&pays=France").json()
    assert page["total"] == 2


def test_filtre_score_minimum(client, base_remplie):
    page = client.get("/api/offres?score_min=70").json()
    assert page["total"] == 2


def test_recherche_plein_texte(client, base_remplie):
    assert client.get("/api/offres?recherche=solvabilité").json()["total"] == 1
    assert client.get("/api/offres?recherche=Banque").json()["total"] == 1


# --- Compteurs de facettes -------------------------------------------------


def test_compteurs_sans_filtre(client, base_remplie):
    compteurs = client.get("/api/offres").json()["compteurs"]
    assert compteurs["contrat"]["CDI"] == 3
    assert compteurs["source"]["civiweb"] == 2
    assert compteurs["pays"]["France"] == 4


def test_un_filtre_ne_s_applique_pas_a_ses_propres_compteurs(client, base_remplie):
    """Sinon, cocher « CDI » afficherait 0 partout ailleurs et on ne pourrait
    plus ajouter un second contrat."""
    compteurs = client.get("/api/offres?contrats=CDI").json()["compteurs"]
    assert compteurs["contrat"]["CDI"] == 3
    assert compteurs["contrat"]["Alternance"] == 1      # toujours visible
    # Les autres facettes, elles, tiennent compte du filtre contrat.
    assert compteurs["pays"]["France"] == 2


# --- Détail ----------------------------------------------------------------


def test_detail_marque_l_offre_comme_vue(client, base_remplie):
    identifiant = client.get("/api/offres").json()["offres"][0]["id"]
    assert client.get("/api/offres/statistiques").json()["jamais_vues"] == 6
    assert client.get(f"/api/offres/{identifiant}").json()["vue"] is True
    assert client.get("/api/offres/statistiques").json()["jamais_vues"] == 5


def test_offre_introuvable(client, base_remplie):
    assert client.get("/api/offres/9999").status_code == 404


def test_le_detail_signale_une_candidature_existante(client, base_remplie, engine):
    identifiant = client.get("/api/offres").json()["offres"][0]["id"]
    with Session(engine) as s:
        s.add(Application(offer_id=identifiant))
        s.commit()
    assert client.get(f"/api/offres/{identifiant}").json()["a_candidature"] is True


# --- Statistiques ----------------------------------------------------------


def test_le_badge_ne_compte_que_la_derniere_recherche(client, base_remplie, engine):
    """Compter toutes les offres jamais ouvertes bloquerait le badge à « 99+ »
    pendant des mois : le signal « il y a du neuf » s'y perdrait."""
    from datetime import timedelta

    from app.models import ScanRun
    from app.models.base import maintenant
    from app.models.enums import StatutScan

    # Sans historique de recherche, il n'y a rien de « nouveau » à annoncer.
    assert client.get("/api/offres/statistiques").json()["nouvelles"] == 0

    with Session(engine) as s:
        # Les six offres de la fixture datent d'« il y a une heure ».
        for offre in s.exec(select(Offer)).all():
            offre.date_recuperation = maintenant() - timedelta(hours=1)
            s.add(offre)
        # Une recherche vient de se terminer : elle n'a rien ramené de nouveau.
        s.add(ScanRun(started_at=maintenant(), statut=StatutScan.TERMINE.value))
        s.commit()

    stats = client.get("/api/offres/statistiques").json()
    assert stats["nouvelles"] == 0, "des offres antérieures au scan ne sont pas nouvelles"
    assert stats["jamais_vues"] == 6, "elles restent non consultées, mais pas nouvelles"


def test_statistiques_pour_l_en_tete(client, base_remplie):
    stats = client.get("/api/offres/statistiques").json()
    assert stats["total"] == 6
    assert stats["aujourd_hui"] == 6
    assert stats["vie"] == 1
    assert stats["non_scorees"] == 1
    assert stats["jamais_vues"] == 6


# --- Scoring ---------------------------------------------------------------


def test_scorer_sans_profil_explique_au_lieu_de_planter(client, base_remplie):
    reponse = client.post("/api/offres/scorer")
    assert reponse.status_code == 409
    assert "profil est vide" in reponse.json()["detail"]


def test_scorer_ne_fait_aucun_appel_llm(client, base_remplie, engine):
    with Session(engine) as s:
        s.add(Profile(skills=[{"nom": "Analyse financière", "ancree": True}],
                      secteurs=["banque"], pays_acceptes=["France"],
                      contrats_acceptes=["CDI"], langues=[{"code": "fr", "niveau": "natif"}]))
        s.commit()

    resultat = client.post("/api/offres/scorer").json()
    assert resultat["appels_llm"] == 0
    assert resultat["scorees"] == 6

    # Relancer sans forcer ne rescore rien : la version des poids n'a pas bougé.
    assert client.post("/api/offres/scorer").json()["scorees"] == 0
    assert client.post("/api/offres/scorer?forcer=true").json()["scorees"] == 6


def test_une_offre_scoree_sans_version_de_poids_est_bien_rescoree(client, base_remplie, engine):
    """Piège SQL : `poids_version != 1` est FAUX quand la colonne vaut NULL.
    Sans traitement explicite, ces offres gardaient un score périmé pour toujours."""
    from sqlmodel import select

    with Session(engine) as s:
        s.add(Profile(skills=[{"nom": "Analyse financière", "ancree": True}],
                      secteurs=["banque"], pays_acceptes=["France"],
                      contrats_acceptes=["CDI"], langues=[{"code": "fr", "niveau": "natif"}]))
        s.commit()
        # État de départ : un score existe, mais aucune version de poids.
        assert all(o.poids_version is None for o in s.exec(select(Offer)).all() if o.score)

    assert client.post("/api/offres/scorer").json()["scorees"] == 6

    with Session(engine) as s:
        assert all(o.poids_version == 1 for o in s.exec(select(Offer)).all())
