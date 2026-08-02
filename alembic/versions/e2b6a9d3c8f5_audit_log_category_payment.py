"""adiciona PAYMENT ao enum audit_log_category

Revision ID: e2b6a9d3c8f5
Revises: d1a5f8c2b9e4
Create Date: 2026-07-30 00:06:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e2b6a9d3c8f5'
down_revision: Union[str, None] = 'd1a5f8c2b9e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_log_category ADD VALUE IF NOT EXISTS 'PAYMENT'")


def downgrade() -> None:
    # Postgres nao suporta remover valor de enum.
    pass
