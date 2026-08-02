"""adiciona coluna analises em permission_settings (quem pode ver/analisar o painel /analises)

Revision ID: d2f6a8c1b4e7
Revises: a1d6e9b3f7c2
Create Date: 2026-07-26 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'd2f6a8c1b4e7'
down_revision: Union[str, None] = 'a1d6e9b3f7c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'permission_settings',
        sa.Column('analises', JSONB, nullable=False, server_default='[]'),
    )


def downgrade() -> None:
    op.drop_column('permission_settings', 'analises')
