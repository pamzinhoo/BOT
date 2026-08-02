"""adiciona coluna shop_message_id em monetization_settings (painel fixo da loja)

Revision ID: d7a2c9e5f1b8
Revises: c6f1a8d4e3b7
Create Date: 2026-07-30 00:11:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7a2c9e5f1b8'
down_revision: Union[str, None] = 'c6f1a8d4e3b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('monetization_settings', sa.Column('shop_message_id', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('monetization_settings', 'shop_message_id')
