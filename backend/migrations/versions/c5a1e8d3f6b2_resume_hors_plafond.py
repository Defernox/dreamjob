"""notifications : le resume du matin ne consomme pas le plafond d'alertes

Revision ID: c5a1e8d3f6b2
Revises: b3f7c2d19e04
Create Date: 2026-09-29 09:00:00

`score_offre.par_resume` : une offre signalée par le résumé du matin, et non
par une alerte de la veille. Le plafond d'alertes du jour comptait les deux :
un résumé de quinze offres faisait taire la veille jusqu'au soir.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5a1e8d3f6b2'
down_revision: Union[str, Sequence[str], None] = 'b3f7c2d19e04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    colonnes = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("score_offre")}
    if "par_resume" not in colonnes:
        # server_default indispensable : la table porte déjà des lignes.
        op.add_column("score_offre", sa.Column("par_resume", sa.Boolean(), nullable=False,
                                               server_default=sa.false()))


def downgrade() -> None:
    op.execute("ALTER TABLE score_offre DROP COLUMN par_resume")
