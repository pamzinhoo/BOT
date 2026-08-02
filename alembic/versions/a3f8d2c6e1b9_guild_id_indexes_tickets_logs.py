"""adiciona indice em guild_id para tickets e logs (consultas guild-scoped sem indice, degradam com o volume)

Revision ID: a3f8d2c6e1b9
Revises: f7a2d5c9b3e1
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a3f8d2c6e1b9'
down_revision: Union[str, None] = 'f7a2d5c9b3e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_tickets_guild_id', 'tickets', ['guild_id'])
    op.create_index('ix_logs_guild_id', 'logs', ['guild_id'])


def downgrade() -> None:
    op.drop_index('ix_logs_guild_id', table_name='logs')
    op.drop_index('ix_tickets_guild_id', table_name='tickets')
