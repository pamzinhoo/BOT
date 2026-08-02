"""adiciona PROCESSING/EXPIRED/CANCELED/CHARGEBACK ao enum payment_status

Revision ID: d1a5f8c2b9e4
Revises: c8a4e1f6b3d9
Create Date: 2026-07-30 00:05:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd1a5f8c2b9e4'
down_revision: Union[str, None] = 'c8a4e1f6b3d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE payment_status ADD VALUE IF NOT EXISTS 'PROCESSING'")
        op.execute("ALTER TYPE payment_status ADD VALUE IF NOT EXISTS 'EXPIRED'")
        op.execute("ALTER TYPE payment_status ADD VALUE IF NOT EXISTS 'CANCELED'")
        op.execute("ALTER TYPE payment_status ADD VALUE IF NOT EXISTS 'CHARGEBACK'")


def downgrade() -> None:
    # Postgres nao suporta remover valor de enum.
    pass
