"""adiciona payer_information em payment_history (texto livre "quem vai pagar", nunca apagado)

Revision ID: e4f9c3a7b2d5
Revises: d3e8b2f6a1c9
Create Date: 2026-08-02 00:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4f9c3a7b2d5'
down_revision: Union[str, None] = 'd3e8b2f6a1c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('payment_history', sa.Column('payer_information', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('payment_history', 'payer_information')
