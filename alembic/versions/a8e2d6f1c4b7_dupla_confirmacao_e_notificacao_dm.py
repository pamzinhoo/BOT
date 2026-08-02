"""dupla confirmacao e notificacao dm antes da punicao — novos status e campos de rastreio

Revision ID: a8e2d6f1c4b7
Revises: f4a1c7e9b3d2
Create Date: 2026-07-26 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8e2d6f1c4b7'
down_revision: Union[str, None] = 'f4a1c7e9b3d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE punishment_status ADD VALUE IF NOT EXISTS 'PENDING' BEFORE 'ACTIVE'")
        op.execute("ALTER TYPE punishment_status ADD VALUE IF NOT EXISTS 'NOTIFIED' BEFORE 'ACTIVE'")

    op.add_column(
        'punishments',
        sa.Column('dm_sent', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )
    op.add_column('punishments', sa.Column('dm_sent_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('punishments', sa.Column('dm_failure_reason', sa.Text(), nullable=True))
    op.add_column('punishments', sa.Column('first_confirmed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('punishments', sa.Column('second_confirmed_at', sa.DateTime(timezone=True), nullable=True))
    op.drop_column('punishments', 'dm_delivered')

    op.alter_column('punishments', 'status', server_default=None)


def downgrade() -> None:
    op.add_column(
        'punishments',
        sa.Column('dm_delivered', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )
    op.drop_column('punishments', 'second_confirmed_at')
    op.drop_column('punishments', 'first_confirmed_at')
    op.drop_column('punishments', 'dm_failure_reason')
    op.drop_column('punishments', 'dm_sent_at')
    op.drop_column('punishments', 'dm_sent')
    # Postgres nao suporta remover valor de enum — PENDING/NOTIFIED ficam no tipo
    # `punishment_status`. Se necessario reverter de verdade, recriar o tipo do zero.
