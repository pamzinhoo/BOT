"""ticket_panel_groups — publicacao combinada de varios paineis de ticket
numa unica mensagem (embed do painel principal + um botao por painel)

Merge de heads: reconcilia os dois heads divergentes deixados pelo merge
87748d2 (retry login 429 + startup migrations + db pool + giveaway +
license/download/player) num unico historico linear.

Revision ID: c7d4a1e8f2b6
Revises: 9f1c7d2a5b4e, e1a9c4f7b3d2
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c7d4a1e8f2b6'
down_revision: Union[str, Sequence[str], None] = ('9f1c7d2a5b4e', 'e1a9c4f7b3d2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# idempotente de proposito: o pooler de transacao do Supabase pode nao manter a
# migration inteira atomica, entao o CREATE checa o catalogo antes de rodar.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'ticket_panel_groups' not in existing_tables:
        op.create_table(
            'ticket_panel_groups',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('panel_ids', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
            sa.Column('channel_id', sa.BigInteger(), nullable=True),
            sa.Column('message_id', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'ix_ticket_panel_groups_guild_id', 'ticket_panel_groups', ['guild_id'], unique=False
        )


def downgrade() -> None:
    op.drop_index('ix_ticket_panel_groups_guild_id', table_name='ticket_panel_groups')
    op.drop_table('ticket_panel_groups')
