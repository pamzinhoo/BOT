"""adiciona expires_at/pix_qr_code/pix_qr_code_base64/checkout_url em payment_history

Revision ID: f3c7b1e4a2d6
Revises: e2b6a9d3c8f5
Create Date: 2026-07-30 00:07:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3c7b1e4a2d6'
down_revision: Union[str, None] = 'e2b6a9d3c8f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('payment_history', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('payment_history', sa.Column('pix_qr_code', sa.Text(), nullable=True))
    op.add_column('payment_history', sa.Column('pix_qr_code_base64', sa.Text(), nullable=True))
    op.add_column('payment_history', sa.Column('checkout_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('payment_history', 'checkout_url')
    op.drop_column('payment_history', 'pix_qr_code_base64')
    op.drop_column('payment_history', 'pix_qr_code')
    op.drop_column('payment_history', 'expires_at')
