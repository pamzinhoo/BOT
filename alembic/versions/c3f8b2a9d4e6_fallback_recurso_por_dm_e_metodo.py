"""fallback de recurso por mensagem dm — metodo do recurso e categoria de auditoria

Revision ID: c3f8b2a9d4e6
Revises: b1c8e4a9d3f5
Create Date: 2026-07-26 16:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f8b2a9d4e6'
down_revision: Union[str, None] = 'b1c8e4a9d3f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    appeal_method = sa.Enum('BUTTON', 'DM_MESSAGE', name='appeal_method')
    appeal_method.create(op.get_bind())
    op.add_column(
        'punishment_appeals',
        sa.Column('method', appeal_method, server_default='BUTTON', nullable=False),
    )

    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_log_category ADD VALUE IF NOT EXISTS 'punishment_appeal'")

    op.add_column(
        'audit_log_settings',
        sa.Column('punishment_appeal', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('audit_log_settings', 'punishment_appeal')
    # Postgres nao suporta remover valor de enum — punishment_appeal fica no tipo
    # `audit_log_category`. Se necessario reverter de verdade, recriar o tipo do zero.

    op.drop_column('punishment_appeals', 'method')
    op.execute('DROP TYPE IF EXISTS appeal_method')
