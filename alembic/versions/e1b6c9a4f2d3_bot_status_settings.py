"""bot status settings — painel de status do bot (canal + intervalo)

Revision ID: e1b6c9a4f2d3
Revises: d2a7c4f8e1b9
Create Date: 2026-07-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1b6c9a4f2d3'
down_revision: Union[str, None] = 'd2a7c4f8e1b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bot_status_settings',
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('channel_id', sa.BigInteger(), nullable=True),
        sa.Column('message_id', sa.BigInteger(), nullable=True),
        sa.Column('update_interval_minutes', sa.Integer(), server_default=sa.text('5'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id'),
    )


def downgrade() -> None:
    op.drop_table('bot_status_settings')
