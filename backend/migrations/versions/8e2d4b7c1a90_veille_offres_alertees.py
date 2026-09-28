"""veille : offres deja alertees

Revision ID: 8e2d4b7c1a90
Revises: 6c1f0a9d2e47
Create Date: 2026-09-28 10:00:00

Une offre signalée par la veille ne doit pas l'être une seconde fois par le
résumé du matin, et le nombre d'alertes du jour est plafonné : les deux se
lisent sur `score_offre.alertee_le`. Colonne facultative : aucune valeur par
défaut à fournir, SQLite l'ajoute sans reconstruire la table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8e2d4b7c1a90'
down_revision: Union[str, Sequence[str], None] = '6c1f0a9d2e47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    colonnes = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("score_offre")}
    if "alertee_le" not in colonnes:
        op.add_column("score_offre", sa.Column("alertee_le", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.execute("ALTER TABLE score_offre DROP COLUMN alertee_le")
