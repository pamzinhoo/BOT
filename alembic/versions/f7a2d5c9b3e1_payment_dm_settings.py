"""cria payment_dm_settings (embed de DM ao comprador na aprovacao/rejeicao de pagamento, por guild)

Revision ID: f7a2d5c9b3e1
Revises: e4f9c3a7b2d5
Create Date: 2026-08-02 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a2d5c9b3e1'
down_revision: Union[str, None] = 'e4f9c3a7b2d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'payment_dm_settings',
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('approved_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('approved_embed_title', sa.String(length=256), nullable=True),
        sa.Column('approved_embed_description', sa.Text(), nullable=True),
        sa.Column('approved_embed_color', sa.Integer(), nullable=True),
        sa.Column('approved_embed_footer', sa.Text(), nullable=True),
        sa.Column('approved_embed_thumbnail_url', sa.Text(), nullable=True),
        sa.Column('approved_embed_image_url', sa.Text(), nullable=True),
        sa.Column('rejected_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('rejected_embed_title', sa.String(length=256), nullable=True),
        sa.Column('rejected_embed_description', sa.Text(), nullable=True),
        sa.Column('rejected_embed_color', sa.Integer(), nullable=True),
        sa.Column('rejected_embed_footer', sa.Text(), nullable=True),
        sa.Column('rejected_embed_thumbnail_url', sa.Text(), nullable=True),
        sa.Column('rejected_embed_image_url', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id'),
    )


def downgrade() -> None:
    op.drop_table('payment_dm_settings')
