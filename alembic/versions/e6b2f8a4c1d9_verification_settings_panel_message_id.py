"""adiciona coluna panel_message_id em verification_settings (painel fixo de verificacao)

Revision ID: e6b2f8a4c1d9
Revises: a1c3e6f9b2d4
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6b2f8a4c1d9'
down_revision: Union[str, None] = 'a1c3e6f9b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('verification_settings', sa.Column('panel_message_id', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('verification_settings', 'panel_message_id')
