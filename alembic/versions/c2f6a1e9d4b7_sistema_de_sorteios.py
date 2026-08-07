"""sistema de sorteios — giveaways, giveaway_entries, giveaway_winners

Revision ID: c2f6a1e9d4b7
Revises: 6ff69141c9a6
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c2f6a1e9d4b7'
down_revision: Union[str, None] = '6ff69141c9a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENUMS = {
    'giveaway_status': ['OPEN', 'CLOSED', 'CANCELED'],
    'giveaway_prize_type': ['ROLE', 'CUSTOM'],
}


# idempotente de proposito: o pooler de transacao do Supabase pode nao manter a
# migration inteira atomica, entao cada CREATE checa o catalogo antes de rodar.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    existing_types = {
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT typname FROM pg_type WHERE typname IN ('giveaway_status', 'giveaway_prize_type')"
            )
        )
    }

    for type_name, values in _ENUMS.items():
        if type_name not in existing_types:
            sa.Enum(*values, name=type_name).create(bind, checkfirst=False)

    status_enum = postgresql.ENUM(*_ENUMS['giveaway_status'], name='giveaway_status', create_type=False)
    prize_type_enum = postgresql.ENUM(
        *_ENUMS['giveaway_prize_type'], name='giveaway_prize_type', create_type=False
    )

    if 'giveaways' not in existing_tables:
        op.create_table(
            'giveaways',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('creator_id', sa.BigInteger(), nullable=False),
            sa.Column('channel_id', sa.BigInteger(), nullable=False),
            sa.Column('message_id', sa.BigInteger(), nullable=True),
            sa.Column('title', sa.String(length=256), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('prize_type', prize_type_enum, server_default=sa.text("'CUSTOM'"), nullable=False),
            sa.Column('prize_role_id', sa.BigInteger(), nullable=True),
            sa.Column('prize_text', sa.String(length=500), nullable=True),
            sa.Column('allowed_role_ids', postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
            sa.Column('winners_count', sa.Integer(), server_default=sa.text('1'), nullable=False),
            sa.Column('status', status_enum, server_default=sa.text("'OPEN'"), nullable=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_giveaways_guild_id', 'giveaways', ['guild_id'], unique=False)
        op.create_index('ix_giveaways_status_expires_at', 'giveaways', ['status', 'expires_at'], unique=False)

    if 'giveaway_entries' not in existing_tables:
        op.create_table(
            'giveaway_entries',
            sa.Column('giveaway_id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['giveaway_id'], ['giveaways.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('giveaway_id', 'user_id', name='uq_giveaway_entry_one_per_user'),
        )
        op.create_index('ix_giveaway_entries_giveaway_id', 'giveaway_entries', ['giveaway_id'], unique=False)

    if 'giveaway_winners' not in existing_tables:
        op.create_table(
            'giveaway_winners',
            sa.Column('giveaway_id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['giveaway_id'], ['giveaways.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_giveaway_winners_giveaway_id', 'giveaway_winners', ['giveaway_id'], unique=False)

    # nova categoria de auditoria pro sistema de sorteios — SQLAlchemy grava o
    # nome do membro do enum (GIVEAWAY), nao o value ("giveaway").
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_log_category ADD VALUE IF NOT EXISTS 'GIVEAWAY'")


def downgrade() -> None:
    op.drop_index('ix_giveaway_winners_giveaway_id', table_name='giveaway_winners')
    op.drop_table('giveaway_winners')

    op.drop_index('ix_giveaway_entries_giveaway_id', table_name='giveaway_entries')
    op.drop_table('giveaway_entries')

    op.drop_index('ix_giveaways_status_expires_at', table_name='giveaways')
    op.drop_index('ix_giveaways_guild_id', table_name='giveaways')
    op.drop_table('giveaways')

    for type_name in _ENUMS:
        op.execute(f'DROP TYPE IF EXISTS {type_name}')
