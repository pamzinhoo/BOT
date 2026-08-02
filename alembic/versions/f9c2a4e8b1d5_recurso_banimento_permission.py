"""adiciona coluna recurso_banimento em permission_settings (quem pode aceitar/negar recurso de banimento)

Revision ID: f9c2a4e8b1d5
Revises: e5b7f3a9c2d4
Create Date: 2026-07-26 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'f9c2a4e8b1d5'
down_revision: Union[str, None] = 'e5b7f3a9c2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'permission_settings',
        sa.Column('recurso_banimento', JSONB, nullable=False, server_default='[]'),
    )


def downgrade() -> None:
    op.drop_column('permission_settings', 'recurso_banimento')
