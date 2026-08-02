"""cria payment_status_history (log append-only de transicoes de status de pagamento)

Revision ID: a4d8e2f6c1b3
Revises: f3c7b1e4a2d6
Create Date: 2026-07-30 00:08:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'a4d8e2f6c1b3'
down_revision: Union[str, None] = 'f3c7b1e4a2d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    payment_status_enum = postgresql.ENUM(name='payment_status', create_type=False)
    op.create_table(
        'payment_status_history',
        sa.Column('payment_id', sa.UUID(), nullable=False),
        sa.Column('previous_status', payment_status_enum, nullable=True),
        sa.Column('new_status', payment_status_enum, nullable=False),
        sa.Column('provider_payload', JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.ForeignKeyConstraint(['payment_id'], ['payment_history.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_payment_status_history_payment_id', 'payment_status_history', ['payment_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_payment_status_history_payment_id', table_name='payment_status_history')
    op.drop_table('payment_status_history')
