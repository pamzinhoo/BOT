"""adiciona coluna giveaway em audit_log_settings

Revision ID: d8b3e5f1a6c9
Revises: c2f6a1e9d4b7
Create Date: 2026-08-07 01:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd8b3e5f1a6c9'
down_revision: Union[str, None] = 'c2f6a1e9d4b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    audit_columns = {column['name'] for column in inspector.get_columns('audit_log_settings')}
    if 'giveaway' not in audit_columns:
        op.add_column(
            'audit_log_settings',
            sa.Column('giveaway', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        )


def downgrade() -> None:
    op.drop_column('audit_log_settings', 'giveaway')
