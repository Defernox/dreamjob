"""comptes et sessions

Revision ID: 34b92e3bf081
Revises: d96aa6480cfe
Create Date: 2026-09-24 06:32:35.459129

Écrite à la main. L'autogénération l'a produite VIDE : les tests démarraient
l'application complète, dont `creer_tables()` sur la vraie base, et les deux
tables y existaient déjà. D'où la création conditionnelle — la migration doit
passer aussi bien sur cette base que sur un serveur neuf.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # types AutoString generes par SQLModel


# revision identifiers, used by Alembic.
revision: str = '34b92e3bf081'
down_revision: Union[str, Sequence[str], None] = 'd96aa6480cfe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existe(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _existe("utilisateur"):
        op.create_table(
            "utilisateur",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("email", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("mot_de_passe", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("cree_le", sa.DateTime(), nullable=False),
            sa.Column("derniere_connexion", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_utilisateur_email", "utilisateur", ["email"], unique=True)
    if not _existe("sessionutilisateur"):
        op.create_table(
            "sessionutilisateur",
            sa.Column("empreinte", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("utilisateur_id", sa.Integer(), nullable=False),
            sa.Column("cree_le", sa.DateTime(), nullable=False),
            sa.Column("expire_le", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["utilisateur_id"], ["utilisateur.id"]),
            sa.PrimaryKeyConstraint("empreinte"),
        )
        op.create_index("ix_sessionutilisateur_utilisateur_id", "sessionutilisateur",
                        ["utilisateur_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_sessionutilisateur_utilisateur_id", table_name="sessionutilisateur")
    op.drop_table("sessionutilisateur")
    op.drop_index("ix_utilisateur_email", table_name="utilisateur")
    op.drop_table("utilisateur")
