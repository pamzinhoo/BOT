"""voice_channel_id em tickets

Revision ID: b4e1f9a2c7d3
Revises: 7a2e8c4f1d9b
Create Date: 2026-07-24 09:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4e1f9a2c7d3'
down_revision: Union[str, None] = '7a2e8c4f1d9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tickets', sa.Column('voice_channel_id', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('tickets', 'voice_channel_id')
