"""sistema de enquetes — polls, poll_options, poll_votes, vote_weights,
enquete_settings

Revision ID: b4e7f2a8c3d6
Revises: a2f5c8d1e4b9
Create Date: 2026-07-30 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b4e7f2a8c3d6'
down_revision: Union[str, None] = 'a2f5c8d1e4b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENUMS = {
    'poll_status': ['OPEN', 'CLOSED', 'CANCELED'],
    'poll_visibility': ['PUBLIC', 'ROLE_RESTRICTED', 'PREMIUM'],
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
                "SELECT typname FROM pg_type WHERE typname IN ('poll_status', 'poll_visibility')"
            )
        )
    }

    for type_name, values in _ENUMS.items():
        if type_name not in existing_types:
            sa.Enum(*values, name=type_name).create(bind, checkfirst=False)

    status_enum = postgresql.ENUM(*_ENUMS['poll_status'], name='poll_status', create_type=False)
    visibility_enum = postgresql.ENUM(*_ENUMS['poll_visibility'], name='poll_visibility', create_type=False)

    if 'polls' not in existing_tables:
        op.create_table(
            'polls',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('creator_id', sa.BigInteger(), nullable=False),
            sa.Column('channel_id', sa.BigInteger(), nullable=False),
            sa.Column('message_id', sa.BigInteger(), nullable=True),
            sa.Column('title', sa.String(length=256), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('status', status_enum, server_default=sa.text("'OPEN'"), nullable=False),
            sa.Column('visibility', visibility_enum, server_default=sa.text("'PUBLIC'"), nullable=False),
            sa.Column('required_role_id', sa.BigInteger(), nullable=True),
            sa.Column('required_plan_id', sa.UUID(), nullable=True),
            sa.Column('weight_mode', sa.String(length=20), server_default=sa.text("'SNAPSHOT'"), nullable=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['required_plan_id'], ['plans.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_polls_guild_id', 'polls', ['guild_id'], unique=False)
        op.create_index('ix_polls_status_expires_at', 'polls', ['status', 'expires_at'], unique=False)

    if 'poll_options' not in existing_tables:
        op.create_table(
            'poll_options',
            sa.Column('poll_id', sa.UUID(), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['poll_id'], ['polls.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_poll_options_poll_id', 'poll_options', ['poll_id'], unique=False)

    if 'poll_votes' not in existing_tables:
        op.create_table(
            'poll_votes',
            sa.Column('poll_id', sa.UUID(), nullable=False),
            sa.Column('option_id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('weight', sa.Integer(), server_default=sa.text('1'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['poll_id'], ['polls.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['option_id'], ['poll_options.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('poll_id', 'user_id', name='uq_poll_vote_one_per_user'),
        )
        op.create_index('ix_poll_votes_poll_id', 'poll_votes', ['poll_id'], unique=False)

    if 'vote_weights' not in existing_tables:
        op.create_table(
            'vote_weights',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('role_id', sa.BigInteger(), nullable=False),
            sa.Column('weight', sa.Integer(), server_default=sa.text('1'), nullable=False),
            sa.Column('source', sa.String(length=20), server_default=sa.text("'MANUAL'"), nullable=False),
            sa.Column('source_plan_id', sa.UUID(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['source_plan_id'], ['plans.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id', 'role_id', name='uq_vote_weight_guild_role'),
        )
        op.create_index('ix_vote_weights_guild_id', 'vote_weights', ['guild_id'], unique=False)

    if 'enquete_settings' not in existing_tables:
        op.create_table(
            'enquete_settings',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('default_weight_mode', sa.String(length=20), server_default=sa.text("'SNAPSHOT'"), nullable=False),
            sa.Column('creation_message', sa.Text(), nullable=True),
            sa.Column('closing_message', sa.Text(), nullable=True),
            sa.Column('result_message', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id'),
        )

    # nova categoria de auditoria pro sistema de enquetes — SQLAlchemy grava o
    # nome do membro do enum (ENQUETE), nao o value ("enquete"), entao e isso
    # que precisa existir no tipo do Postgres (ver e5b7f3a9c2d4).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_log_category ADD VALUE IF NOT EXISTS 'ENQUETE'")


def downgrade() -> None:
    op.drop_table('enquete_settings')

    op.drop_index('ix_vote_weights_guild_id', table_name='vote_weights')
    op.drop_table('vote_weights')

    op.drop_index('ix_poll_votes_poll_id', table_name='poll_votes')
    op.drop_table('poll_votes')

    op.drop_index('ix_poll_options_poll_id', table_name='poll_options')
    op.drop_table('poll_options')

    op.drop_index('ix_polls_status_expires_at', table_name='polls')
    op.drop_index('ix_polls_guild_id', table_name='polls')
    op.drop_table('polls')

    for type_name in _ENUMS:
        op.execute(f'DROP TYPE IF EXISTS {type_name}')
