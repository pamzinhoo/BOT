"""guilds registry — tabela de tenant, populada de forma lazy pelo bot

Revision ID: a2f5c8d1e4b9
Revises: c4f9a6e1b8d3
Create Date: 2026-07-30 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2f5c8d1e4b9'
down_revision: Union[str, None] = 'c4f9a6e1b8d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# idempotente de proposito: o pooler de transacao do Supabase pode nao manter a
# migration inteira atomica, entao cada CREATE checa o catalogo antes de rodar.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'guilds' not in existing_tables:
        op.create_table(
            'guilds',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('name', sa.String(length=200), nullable=False),
            sa.Column('owner_id', sa.BigInteger(), nullable=False),
            sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id'),
        )
        op.create_index('ix_guilds_guild_id', 'guilds', ['guild_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_guilds_guild_id', table_name='guilds')
    op.drop_table('guilds')
