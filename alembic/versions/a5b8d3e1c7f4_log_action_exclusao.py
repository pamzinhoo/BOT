"""adiciona EXCLUSAO ao enum log_action

Revision ID: a5b8d3e1c7f4
Revises: f4a1c8d5e2b6
Create Date: 2026-07-31 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a5b8d3e1c7f4'
down_revision: Union[str, None] = 'f4a1c8d5e2b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE log_action ADD VALUE IF NOT EXISTS 'EXCLUSAO'")


def downgrade() -> None:
    # Postgres nao suporta remover valor de enum.
    pass
