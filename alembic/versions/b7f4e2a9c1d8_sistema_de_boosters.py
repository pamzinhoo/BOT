"""sistema de boosters — boosters, booster_settings

Revision ID: b7f4e2a9c1d8
Revises: a3c7f1e9b2d4
Create Date: 2026-07-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f4e2a9c1d8'
down_revision: Union[str, None] = 'a3c7f1e9b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# idempotente de proposito: o pooler de transacao do Supabase pode nao manter a
# migration inteira atomica, entao cada CREATE checa o catalogo antes de rodar
# pra suportar reexecucao apos uma falha parcial sem precisar de limpeza manual.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'boosters' not in existing_tables:
        op.create_table(
            'boosters',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('boost_since', sa.DateTime(timezone=True), nullable=True),
            sa.Column('boost_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
            sa.Column('currently_boosting', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('last_removed', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id', 'user_id', name='uq_boosters_guild_user'),
        )
        op.create_index('ix_boosters_guild_id', 'boosters', ['guild_id'], unique=False)

    if 'booster_settings' not in existing_tables:
        op.create_table(
            'booster_settings',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('booster_role_id', sa.BigInteger(), nullable=True),
            sa.Column('dm_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('dm_message', sa.Text(), nullable=True),
            sa.Column('log_channel_id', sa.BigInteger(), nullable=True),
            sa.Column('public_message_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('public_channel_id', sa.BigInteger(), nullable=True),
            sa.Column('public_message', sa.Text(), nullable=True),
            sa.Column('public_use_embed', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id'),
        )


def downgrade() -> None:
    op.drop_table('booster_settings')

    op.drop_index('ix_boosters_guild_id', table_name='boosters')
    op.drop_table('boosters')
