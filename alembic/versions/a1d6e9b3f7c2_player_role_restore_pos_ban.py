"""adiciona player_role_id em guild_settings (cargo devolvido ao reentrar apos ban revogado)

Revision ID: a1d6e9b3f7c2
Revises: f9c2a4e8b1d5
Create Date: 2026-07-26 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1d6e9b3f7c2'
down_revision: Union[str, None] = 'f9c2a4e8b1d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('guild_settings', sa.Column('player_role_id', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('guild_settings', 'player_role_id')
