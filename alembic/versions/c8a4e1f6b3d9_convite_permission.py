"""adiciona coluna convite em permission_settings (quem pode criar convites do servidor)

Revision ID: c8a4e1f6b3d9
Revises: b4e7f2a8c3d6
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'c8a4e1f6b3d9'
down_revision: Union[str, None] = 'b4e7f2a8c3d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'permission_settings',
        sa.Column('convite', JSONB, nullable=False, server_default='[]'),
    )


def downgrade() -> None:
    op.drop_column('permission_settings', 'convite')
