"""Les garde-fous du schéma : déduplication et unicité des candidatures.

Ces contraintes sont ce qui empêche « relancer un scan deux fois » de polluer
la base. Elles sont vérifiées ici au niveau SQL, pas seulement dans le code.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Application, LlmCache, Offer, Profile


def _offre(**kw) -> Offer:
    base = dict(source="france_travail", source_id="ABC123", titre="Chef de projet",
                entreprise="Acme", pays="France", hash="h1")
    return Offer(**{**base, **kw})


def test_meme_source_et_source_id_refuses(session):
    session.add(_offre())
    session.commit()
    session.add(_offre(hash="h2"))          # hash différent, mais même identifiant source
    with pytest.raises(IntegrityError):
        session.commit()


def test_meme_hash_refuse_entre_deux_sources(session):
    """La même annonce republiée ailleurs ne crée pas de doublon."""
    session.add(_offre())
    session.commit()
    session.add(_offre(source="adzuna", source_id="XYZ", hash="h1"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_une_seule_candidature_par_offre(session):
    offre = _offre()
    session.add(offre)
    session.commit()
    session.add(Application(offer_id=offre.id))
    session.commit()
    session.add(Application(offer_id=offre.id))   # double clic sur « Postuler »
    with pytest.raises(IntegrityError):
        session.commit()


def test_champs_json_survivent_a_un_aller_retour(session):
    profil = Profile(
        prenom="Maxim",
        skills=[{"nom": "YouTube", "niveau": "avancé", "ancree": True},
                {"nom": "Excel", "niveau": "courant", "ancree": False}],
        langues=[{"code": "fr", "libelle": "Français", "niveau": "natif"}],
        experiences=[{"entreprise": "Acme", "poste": "Chargé de com"}],
    )
    session.add(profil)
    session.commit()
    session.refresh(profil)

    assert profil.noms_skills() == ["YouTube", "Excel"]
    assert profil.skills_ancrees() == ["YouTube"]
    assert profil.codes_langues() == ["fr"]
    assert profil.entreprises_connues() == ["Acme"]


def test_cle_de_cache_llm_est_stable_et_discriminante():
    a = LlmCache.construire_cle("extraction", "h1", "claude-sonnet-5")
    b = LlmCache.construire_cle("extraction", "h1", "claude-sonnet-5")
    c = LlmCache.construire_cle("extraction", "h1", "autre-modele")
    d = LlmCache.construire_cle("lettre", "h1", "claude-sonnet-5")
    assert a == b          # même appel => cache réutilisé, zéro requête LLM
    assert a != c != d     # modèle ou type différent => entrée distincte


def test_les_pragmas_sqlite_sont_bien_appliques():
    """Trois réglages sans lesquels la base ment ou perd des données."""
    from sqlmodel import Session, create_engine, text

    from app.db import _pragmas_sqlite  # noqa: F401  (l'import branche l'écouteur)

    moteur = create_engine("sqlite://")   # en mémoire : hérite des mêmes pragmas
    with Session(moteur) as s:
        assert s.exec(text("PRAGMA foreign_keys")).one()[0] == 1, \
            "sans cela, SQLite ignore silencieusement les clés étrangères"
        assert s.exec(text("PRAGMA synchronous")).one()[0] == 2, \
            "FULL (2) : une transaction validée ne doit pas se perdre"
