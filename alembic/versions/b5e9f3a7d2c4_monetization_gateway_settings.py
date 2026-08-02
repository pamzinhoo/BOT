"""cria monetization_gateway_settings (config de gateway de pagamento por guild)

Revision ID: b5e9f3a7d2c4
Revises: a4d8e2f6c1b3
Create Date: 2026-07-30 00:09:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5e9f3a7d2c4'
down_revision: Union[str, None] = 'a4d8e2f6c1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'monetization_gateway_settings',
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('provider', sa.String(length=30), server_default=sa.text("'manual'"), nullable=False),
        sa.Column('environment', sa.String(length=20), server_default=sa.text("'sandbox'"), nullable=False),
        sa.Column('currency', sa.String(length=8), server_default=sa.text("'BRL'"), nullable=False),
        sa.Column('pix_expiration_minutes', sa.Integer(), server_default=sa.text('30'), nullable=False),
        sa.Column('allow_recurring', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('allow_one_time', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('enable_pix', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('enable_card', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('enable_boleto', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id'),
    )


def downgrade() -> None:
    op.drop_table('monetization_gateway_settings')
