"""Télécharger ses documents depuis l'interface — indispensable sur un serveur."""

import json

import pytest

from app.config import reglages
from app.models import Offer


@pytest.fixture
def dossier(tmp_path, monkeypatch, session):
    monkeypatch.setattr(reglages().chemins, "dossier_candidatures", str(tmp_path))
    offre = Offer(source="france_travail", source_id="42", titre="Analyste", entreprise="Banque",
                  hash="h42")
    session.add(offre)
    session.commit()
    session.refresh(offre)

    d = tmp_path / "2026-09-24-banque-analyste"
    d.mkdir()
    (d / "offre.json").write_text(json.dumps({"source": "france_travail", "source_id": "42"}),
                                  encoding="utf-8")
    (d / "CV_Maxime_Nicolas.pdf").write_bytes(b"%PDF-cv")
    (d / "CV_Maxime_Nicolas.docx").write_bytes(b"docx")
    (d / "notes-perso.txt").write_text("à ne pas servir", encoding="utf-8")
    (tmp_path / "secret.pdf").write_bytes(b"hors du dossier")
    return offre


def test_les_documents_d_une_offre_sont_listes_pdf_en_tete(client, dossier):
    reponse = client.get(f"/api/offres/{dossier.id}/documents").json()
    assert [f["nom"] for f in reponse["fichiers"]] == ["CV_Maxime_Nicolas.pdf",
                                                       "CV_Maxime_Nicolas.docx"]


def test_un_document_se_telecharge(client, dossier):
    reponse = client.get(f"/api/offres/{dossier.id}/documents/CV_Maxime_Nicolas.pdf")
    assert reponse.status_code == 200
    assert reponse.content == b"%PDF-cv"
    assert "attachment" in reponse.headers["content-disposition"]


@pytest.mark.parametrize("nom", [
    "notes-perso.txt",          # un fichier de l'utilisateur, d'un type non servi
    "..%2Fsecret.pdf",          # remonter d'un dossier
    "..%2F..%2F.env",
    "inexistant.pdf",
])
def test_rien_d_autre_ne_sort(client, dossier, nom):
    assert client.get(f"/api/offres/{dossier.id}/documents/{nom}").status_code == 404


def test_une_offre_sans_dossier_n_a_aucun_document(client, session, dossier):
    autre = Offer(source="adzuna", source_id="7", titre="Autre", hash="h7")
    session.add(autre)
    session.commit()
    session.refresh(autre)
    assert client.get(f"/api/offres/{autre.id}/documents").json() == {"dossier": None,
                                                                      "fichiers": []}
