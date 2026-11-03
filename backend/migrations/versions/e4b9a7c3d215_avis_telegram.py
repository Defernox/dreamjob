"""notifications : l'avis donné d'un appui sous une alerte Telegram

Revision ID: e4b9a7c3d215
Revises: c5a1e8d3f6b2
Create Date: 2026-11-03 04:00:00

`score_offre.avis` (1 intéressant, 0 pas pour moi) et `score_offre.avis_le` :
les réponses aux boutons des alertes, gardées comme étiquettes pour mesurer le
score. Deux colonnes facultatives : aucune valeur par défaut à fournir, aucune
table reconstruite.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e4b9a7c3d215'
down_revision: Union[str, Sequence[str], None] = 'c5a1e8d3f6b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    colonnes = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("score_offre")}
    if "avis" not in colonnes:
        op.add_column("score_offre", sa.Column("avis", sa.Integer(), nullable=True))
    if "avis_le" not in colonnes:
        op.add_column("score_offre", sa.Column("avis_le", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.execute("ALTER TABLE score_offre DROP COLUMN avis_le")
    op.execute("ALTER TABLE score_offre DROP COLUMN avis")
