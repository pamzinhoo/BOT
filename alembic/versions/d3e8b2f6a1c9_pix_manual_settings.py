"""cria pix_manual_settings (chave PIX/recebedor por guild, usado pelo ManualProvider pra gerar QR local)

Revision ID: d3e8b2f6a1c9
Revises: a5b8d3e1c7f4
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3e8b2f6a1c9'
down_revision: Union[str, None] = 'a5b8d3e1c7f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pix_manual_settings',
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('pix_key_type', sa.String(length=20), nullable=True),
        sa.Column('pix_key', sa.Text(), nullable=True),
        sa.Column('receiver_name', sa.String(length=100), nullable=True),
        sa.Column('receiver_city', sa.String(length=50), nullable=True),
        sa.Column('bank_name', sa.String(length=100), nullable=True),
        sa.Column('buyer_message', sa.Text(), nullable=True),
        sa.Column('expiration_minutes', sa.Integer(), server_default=sa.text('60'), nullable=False),
        sa.Column('send_qr_code', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('send_copy_paste', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('manual_approval', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id'),
    )


def downgrade() -> None:
    op.drop_table('pix_manual_settings')
