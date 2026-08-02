"""adiciona PLAN ao enum audit_log_category

Revision ID: f4a1c8d5e2b6
Revises: f1a9c6e3b7d2
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f4a1c8d5e2b6'
down_revision: Union[str, None] = 'f1a9c6e3b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    audit_columns = {column['name'] for column in inspector.get_columns('audit_log_settings')}
    if 'plan' not in audit_columns:
        op.add_column(
            'audit_log_settings',
            sa.Column('plan', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        )

    # SQLAlchemy grava o NOME do membro do enum (PLAN), nao o value ("plan").
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_log_category ADD VALUE IF NOT EXISTS 'PLAN'")


def downgrade() -> None:
    op.drop_column('audit_log_settings', 'plan')
    # Postgres nao suporta remover valor de enum.
