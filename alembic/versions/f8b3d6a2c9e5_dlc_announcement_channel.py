"""adiciona coluna dlc_announcement_channel_id em monetization_settings (aviso automatico de DLC gratuita)

Revision ID: f8b3d6a2c9e5
Revises: e2c5f9a1d6b3
Create Date: 2026-08-21 18:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8b3d6a2c9e5'
down_revision: Union[str, None] = 'e2c5f9a1d6b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'monetization_settings',
        sa.Column('dlc_announcement_channel_id', sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('monetization_settings', 'dlc_announcement_channel_id')
