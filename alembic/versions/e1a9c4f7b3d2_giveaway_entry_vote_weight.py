"""adiciona peso de voto (VIP) as participacoes de sorteio

Revision ID: e1a9c4f7b3d2
Revises: d8b3e5f1a6c9
Create Date: 2026-08-07 02:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e1a9c4f7b3d2'
down_revision: Union[str, None] = 'd8b3e5f1a6c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column['name'] for column in inspector.get_columns('giveaway_entries')}
    if 'weight' not in columns:
        op.add_column(
            'giveaway_entries',
            sa.Column('weight', sa.Integer(), server_default=sa.text('1'), nullable=False),
        )


def downgrade() -> None:
    op.drop_column('giveaway_entries', 'weight')
