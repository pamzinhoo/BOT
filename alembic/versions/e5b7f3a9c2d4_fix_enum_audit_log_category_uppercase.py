"""corrige valores do enum audit_log_category para maiusculo (sqlalchemy grava o nome, nao o value)

Revision ID: e5b7f3a9c2d4
Revises: d7e4a2c1f9b8
Create Date: 2026-07-26 20:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e5b7f3a9c2d4'
down_revision: Union[str, None] = 'd7e4a2c1f9b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_log_category ADD VALUE IF NOT EXISTS 'PUNISHMENT_APPEAL'")
        op.execute("ALTER TYPE audit_log_category ADD VALUE IF NOT EXISTS 'PUNISHMENT_REVIEW'")


def downgrade() -> None:
    # Postgres nao suporta remover valor de enum.
    pass
