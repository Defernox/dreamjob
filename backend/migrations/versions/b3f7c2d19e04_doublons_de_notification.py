"""notifications : le meme poste ne sonne qu'une fois

Revision ID: b3f7c2d19e04
Revises: 8e2d4b7c1a90
Create Date: 2026-09-29 04:00:00

`score_offre.doublon_de` : une offre reconnue comme le même poste qu'une offre
déjà signalée (autre source, autre agence) est marquée signalée par son jumeau,
sans avoir sonné. Colonne facultative, ajoutée sans reconstruire la table.

Au passage, les intitulés des sites d'employeurs arrivés échappés en HTML
(« Monitoring &amp; Management », Beesite) sont rétablis : le connecteur les
désechappe désormais, les anciens seraient restés illisibles.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3f7c2d19e04'
down_revision: Union[str, Sequence[str], None] = '8e2d4b7c1a90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    colonnes = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("score_offre")}
    if "doublon_de" not in colonnes:
        op.add_column("score_offre", sa.Column("doublon_de", sa.Integer(), nullable=True))
    op.execute("UPDATE offer SET titre = REPLACE(titre, '&amp;', '&') "
               "WHERE source = 'employeurs' AND titre LIKE '%&amp;%'")


def downgrade() -> None:
    op.execute("ALTER TABLE score_offre DROP COLUMN doublon_de")
