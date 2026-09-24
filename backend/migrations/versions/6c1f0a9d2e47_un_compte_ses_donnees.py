"""un compte, ses donnees

Revision ID: 6c1f0a9d2e47
Revises: 34b92e3bf081
Create Date: 2026-09-24 12:00:00

Écrite à la main, sans reconstruction de table : la base active les clés
étrangères (`PRAGMA foreign_keys=ON`), et le mode « batch » d'Alembic — copier
une table, supprimer l'ancienne — échouerait sur `offer`, que d'autres tables
référencent. Tout passe donc par ADD COLUMN, DROP COLUMN et des index.

Les données d'avant les comptes reviennent au propriétaire : le plus ancien
compte s'il en existe un, sinon un compte « local » créé ici, que le premier
`python -m app.compte creer` reprendra.
"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # types AutoString generes par SQLModel


# revision identifiers, used by Alembic.
revision: str = '6c1f0a9d2e47'
down_revision: Union[str, Sequence[str], None] = '34b92e3bf081'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Les extraits de lettres qui vivaient dans le code (documents/exemples.py) :
# ce sont les phrases du propriétaire, ils rejoignent son profil.
EXEMPLES_DU_PROPRIETAIRE = """✓ « Anciennement Gestionnaire de Portefeuille Export au Crédit Mutuel et diplômé
   du Master 2 PGE Finance de l'EM Normandie (mémoire noté 16,75/20) »
   → J'ouvre sur mon statut et une preuve chiffrée. Jamais sur mon intérêt.

✓ « gérer quotidiennement un portefeuille de 15 à 25 entreprises représentant un
   chiffre d'affaires de 50 à 75 millions d'euros »
   → Le fait porte seul, sans adjectif ajouté.

✓ « l'augmentation de 100 % de la trésorerie associative et la réussite d'un
   crowdfunding à 150 % des objectifs »
   → Un résultat rendu crédible par le chiffre.

✗ « Je serais ravi de vous rencontrer » — formule vide.
✗ « mon dynamisme, mon sérieux et ma volonté » — trois qualités auto-attribuées.
✗ « un environnement stimulant » — vrai de n'importe quelle entreprise."""


def _existe(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _colonnes(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _index(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _maintenant() -> str:
    # Le format que SQLAlchemy écrit lui-même dans SQLite.
    return datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")


def _ajouter_reference(table: str) -> None:
    """ADD COLUMN avec sa clé étrangère : SQLite l'accepte tant que la valeur
    par défaut est NULL, sans reconstruire la table."""
    if "utilisateur_id" not in _colonnes(table):
        op.execute(f"ALTER TABLE {table} ADD COLUMN utilisateur_id INTEGER "
                   f"REFERENCES utilisateur (id)")


def upgrade() -> None:
    bind = op.get_bind()

    # --- Comptes ---------------------------------------------------------
    if "proprietaire" not in _colonnes("utilisateur"):
        op.add_column("utilisateur", sa.Column("proprietaire", sa.Boolean(), nullable=False,
                                               server_default=sa.false()))
    if "budget_mensuel_usd" not in _colonnes("utilisateur"):
        op.add_column("utilisateur", sa.Column("budget_mensuel_usd", sa.Float(), nullable=True))

    proprio = bind.execute(sa.text("SELECT id FROM utilisateur ORDER BY id LIMIT 1")).scalar()
    if proprio is None:
        bind.execute(sa.text(
            "INSERT INTO utilisateur (email, mot_de_passe, cree_le, proprietaire) "
            "VALUES ('local', '', :le, 1)"), {"le": _maintenant()})
        proprio = bind.execute(sa.text("SELECT id FROM utilisateur ORDER BY id LIMIT 1")).scalar()
    else:
        bind.execute(sa.text("UPDATE utilisateur SET proprietaire = 1 WHERE id = :id"),
                     {"id": proprio})

    # --- Profil ----------------------------------------------------------
    _ajouter_reference("profile")
    for colonne in ("exemples_style", "ntfy_sujet"):
        if colonne not in _colonnes("profile"):
            op.add_column("profile", sa.Column(colonne, sqlmodel.sql.sqltypes.AutoString(),
                                               nullable=False, server_default=""))
    if "ix_profile_utilisateur_id" not in _index("profile"):
        op.create_index("ix_profile_utilisateur_id", "profile", ["utilisateur_id"], unique=True)
    if bind.execute(sa.text("SELECT 1 FROM profile WHERE utilisateur_id = :id"),
                    {"id": proprio}).first() is None:
        bind.execute(sa.text(
            "UPDATE profile SET utilisateur_id = :id "
            "WHERE id = (SELECT MIN(id) FROM profile) AND utilisateur_id IS NULL"), {"id": proprio})
    bind.execute(sa.text(
        "UPDATE profile SET exemples_style = :texte "
        "WHERE utilisateur_id = :id AND exemples_style = ''"),
        {"texte": EXEMPLES_DU_PROPRIETAIRE, "id": proprio})

    # --- Candidatures : uniques par compte, plus dans l'absolu -----------
    _ajouter_reference("application")
    if "ix_application_offer_id" in _index("application"):
        op.drop_index("ix_application_offer_id", table_name="application")
    op.create_index("ix_application_offer_id", "application", ["offer_id"], unique=False)
    if "ix_application_utilisateur_id" not in _index("application"):
        op.create_index("ix_application_utilisateur_id", "application", ["utilisateur_id"])
    bind.execute(sa.text("UPDATE application SET utilisateur_id = :id "
                         "WHERE utilisateur_id IS NULL"), {"id": proprio})
    if "ix_application_utilisateur_offre" not in _index("application"):
        op.create_index("ix_application_utilisateur_offre", "application",
                        ["utilisateur_id", "offer_id"], unique=True)

    # --- Recherches : un nom unique par compte ---------------------------
    _ajouter_reference("recherche")
    if "ix_recherche_nom" in _index("recherche"):
        op.drop_index("ix_recherche_nom", table_name="recherche")
    op.create_index("ix_recherche_nom", "recherche", ["nom"], unique=False)
    if "ix_recherche_utilisateur_id" not in _index("recherche"):
        op.create_index("ix_recherche_utilisateur_id", "recherche", ["utilisateur_id"])
    bind.execute(sa.text("UPDATE recherche SET utilisateur_id = :id "
                         "WHERE utilisateur_id IS NULL"), {"id": proprio})
    if "ix_recherche_utilisateur_nom" not in _index("recherche"):
        op.create_index("ix_recherche_utilisateur_nom", "recherche",
                        ["utilisateur_id", "nom"], unique=True)

    # --- Scans : ceux d'avant les comptes, planifiés compris, n'ont été ----
    # joués que pour le propriétaire. Laissés communs, ils s'afficheraient chez
    # un ami comme sa « dernière recherche », avec les nouveautés d'un autre.
    _ajouter_reference("scan_run")
    if "ix_scan_run_utilisateur_id" not in _index("scan_run"):
        op.create_index("ix_scan_run_utilisateur_id", "scan_run", ["utilisateur_id"])
    bind.execute(sa.text("UPDATE scan_run SET utilisateur_id = :id WHERE utilisateur_id IS NULL"),
                 {"id": proprio})

    # --- Scores : de l'offre vers le compte ------------------------------
    if not _existe("score_offre"):
        op.create_table(
            "score_offre",
            sa.Column("utilisateur_id", sa.Integer(), nullable=False),
            sa.Column("offer_id", sa.Integer(), nullable=False),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("score_detail", sa.JSON(), nullable=False),
            sa.Column("score_explication", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("scored_at", sa.DateTime(), nullable=True),
            sa.Column("poids_version", sa.Integer(), nullable=True),
            sa.Column("version_signaux", sa.Integer(), nullable=True),
            sa.Column("vue", sa.Boolean(), nullable=False),
            sa.Column("ajoutee_le", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["offer_id"], ["offer.id"]),
            sa.ForeignKeyConstraint(["utilisateur_id"], ["utilisateur.id"]),
            sa.PrimaryKeyConstraint("utilisateur_id", "offer_id"),
        )
        op.create_index("ix_score_offre_offer_id", "score_offre", ["offer_id"])
        op.create_index("ix_score_offre_ajoutee_le", "score_offre", ["ajoutee_le"])
        op.create_index("ix_score_offre_utilisateur_score", "score_offre",
                        ["utilisateur_id", "score"])
        op.create_index("ix_score_offre_utilisateur_vue", "score_offre",
                        ["utilisateur_id", "vue"])

    anciennes = _colonnes("offer")
    if "score" in anciennes:
        # Toutes les offres existantes entrent dans le fil du propriétaire, avec
        # sa note et ce qu'il a déjà ouvert : rien ne bouge pour lui.
        bind.execute(sa.text(
            "INSERT INTO score_offre (utilisateur_id, offer_id, score, score_detail, "
            "score_explication, scored_at, poids_version, version_signaux, vue, ajoutee_le) "
            "SELECT :id, o.id, o.score, COALESCE(o.score_detail, '{}'), "
            "COALESCE(o.score_explication, ''), o.scored_at, o.poids_version, "
            "json_extract(o.extraction, '$.version'), COALESCE(o.vue, 0), o.date_recuperation "
            "FROM offer o WHERE NOT EXISTS (SELECT 1 FROM score_offre s "
            "WHERE s.utilisateur_id = :id AND s.offer_id = o.id)"), {"id": proprio})

        for index in ("ix_offer_score", "ix_offer_vue"):
            if index in _index("offer"):
                op.drop_index(index, table_name="offer")
        for colonne in ("score", "score_detail", "score_explication", "scored_at",
                        "poids_version", "vue"):
            if colonne in _colonnes("offer"):
                op.execute(f"ALTER TABLE offer DROP COLUMN {colonne}")

    # --- Dépenses d'API, pour le budget des comptes amis -----------------
    if not _existe("depense_llm"):
        op.create_table(
            "depense_llm",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("utilisateur_id", sa.Integer(), nullable=False),
            sa.Column("offer_id", sa.Integer(), nullable=True),
            sa.Column("le", sa.DateTime(), nullable=False),
            sa.Column("cout_usd", sa.Float(), nullable=False),
            sa.ForeignKeyConstraint(["offer_id"], ["offer.id"]),
            sa.ForeignKeyConstraint(["utilisateur_id"], ["utilisateur.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_depense_llm_utilisateur_id", "depense_llm", ["utilisateur_id"])
        op.create_index("ix_depense_llm_le", "depense_llm", ["le"])


def downgrade() -> None:
    """Retour au mono-compte, avec perte : seules les données du propriétaire
    survivent. Les colonnes `utilisateur_id` restent en place — SQLite refuse
    de supprimer une colonne porteuse d'une clé étrangère sans reconstruire la
    table, et une colonne de trop ne gêne pas l'ancien code."""
    bind = op.get_bind()
    proprio = bind.execute(sa.text(
        "SELECT id FROM utilisateur ORDER BY proprietaire DESC, id LIMIT 1")).scalar()

    op.add_column("offer", sa.Column("score", sa.Float(), nullable=True))
    op.add_column("offer", sa.Column("score_detail", sa.JSON(), nullable=False,
                                     server_default="{}"))
    op.add_column("offer", sa.Column("score_explication", sqlmodel.sql.sqltypes.AutoString(),
                                     nullable=False, server_default=""))
    op.add_column("offer", sa.Column("scored_at", sa.DateTime(), nullable=True))
    op.add_column("offer", sa.Column("poids_version", sa.Integer(), nullable=True))
    op.add_column("offer", sa.Column("vue", sa.Boolean(), nullable=False,
                                     server_default=sa.false()))
    if proprio is not None:
        bind.execute(sa.text(
            "UPDATE offer SET score = s.score, score_detail = s.score_detail, "
            "score_explication = s.score_explication, scored_at = s.scored_at, "
            "poids_version = s.poids_version, vue = s.vue "
            "FROM score_offre s WHERE s.offer_id = offer.id AND s.utilisateur_id = :id"),
            {"id": proprio})
        for table in ("application", "recherche", "profile"):
            bind.execute(sa.text(f"DELETE FROM {table} WHERE utilisateur_id IS NOT NULL "
                                 f"AND utilisateur_id != :id"), {"id": proprio})
    op.create_index("ix_offer_score", "offer", ["score"])
    op.create_index("ix_offer_vue", "offer", ["vue"])

    op.drop_table("depense_llm")
    op.drop_table("score_offre")

    op.drop_index("ix_recherche_utilisateur_nom", table_name="recherche")
    op.drop_index("ix_recherche_nom", table_name="recherche")
    op.create_index("ix_recherche_nom", "recherche", ["nom"], unique=True)
    op.drop_index("ix_application_utilisateur_offre", table_name="application")
    op.drop_index("ix_application_offer_id", table_name="application")
    op.create_index("ix_application_offer_id", "application", ["offer_id"], unique=True)

    op.execute("ALTER TABLE profile DROP COLUMN exemples_style")
    op.execute("ALTER TABLE profile DROP COLUMN ntfy_sujet")
    op.execute("ALTER TABLE utilisateur DROP COLUMN budget_mensuel_usd")
    op.execute("ALTER TABLE utilisateur DROP COLUMN proprietaire")
