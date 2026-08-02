"""sistema de verificacao/captcha — verification_settings, verification_sessions

Revision ID: b9c0ec638585
Revises: a3f8d2c6e1b9
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b9c0ec638585'
down_revision: Union[str, None] = 'a3f8d2c6e1b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# idempotente de proposito: o pooler de transacao do Supabase pode nao manter a
# migration inteira atomica (uma DDL fica commitada mesmo se a proxima falhar),
# entao cada CREATE checa o catalogo antes de rodar pra suportar reexecucao
# apos uma falha parcial sem precisar de limpeza manual no banco.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_types = {
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT typname FROM pg_type WHERE typname IN "
                "('verification_method', 'verification_session_status')"
            )
        )
    }

    _METHOD_ENUM = postgresql.ENUM(
        'TYPE', 'BUTTON', 'RANDOM', name='verification_method', create_type=False
    )
    _STATUS_ENUM = postgresql.ENUM(
        'PENDING', 'SUCCEEDED', 'EXPIRED', 'MAX_ATTEMPTS_EXCEEDED', 'CANCELLED',
        name='verification_session_status', create_type=False,
    )

    if 'verification_method' not in existing_types:
        sa.Enum('TYPE', 'BUTTON', 'RANDOM', name='verification_method').create(bind, checkfirst=False)
    if 'verification_session_status' not in existing_types:
        sa.Enum(
            'PENDING', 'SUCCEEDED', 'EXPIRED', 'MAX_ATTEMPTS_EXCEEDED', 'CANCELLED',
            name='verification_session_status',
        ).create(bind, checkfirst=False)

    existing_tables = set(inspector.get_table_names())

    if 'verification_settings' not in existing_tables:
        op.create_table(
            'verification_settings',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('method', sa.String(length=20), server_default='type', nullable=False),
            sa.Column('unverified_role_id', sa.BigInteger(), nullable=True),
            sa.Column('verified_role_id', sa.BigInteger(), nullable=True),
            sa.Column('verification_channel_id', sa.BigInteger(), nullable=True),
            sa.Column('log_channel_id', sa.BigInteger(), nullable=True),
            sa.Column('code_length', sa.Integer(), server_default=sa.text('6'), nullable=False),
            sa.Column(
                'code_charset', sa.String(length=20), server_default='alphanumeric', nullable=False
            ),
            sa.Column('case_sensitive', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('max_attempts', sa.Integer(), server_default=sa.text('3'), nullable=False),
            sa.Column('timeout_minutes', sa.Integer(), server_default=sa.text('10'), nullable=False),
            sa.Column('welcome_message', sa.Text(), nullable=True),
            sa.Column('success_message', sa.Text(), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('expired_message', sa.Text(), nullable=True),
            sa.Column('max_attempts_message', sa.Text(), nullable=True),
            sa.Column(
                'on_max_attempts_action', sa.String(length=20), server_default='none', nullable=False
            ),
            sa.Column('on_expire_action', sa.String(length=20), server_default='none', nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id'),
        )

    if 'verification_sessions' not in existing_tables:
        op.create_table(
            'verification_sessions',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('method', _METHOD_ENUM, nullable=False),
            sa.Column('code', sa.String(length=16), nullable=False),
            sa.Column('case_sensitive', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column(
                'decoys', postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"), nullable=False,
            ),
            sa.Column('generation', sa.Integer(), server_default=sa.text('1'), nullable=False),
            sa.Column('status', _STATUS_ENUM, server_default='PENDING', nullable=False),
            sa.Column('attempts_used', sa.Integer(), server_default=sa.text('0'), nullable=False),
            sa.Column('max_attempts', sa.Integer(), nullable=False),
            sa.Column('via_dm', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('delivery_channel_id', sa.BigInteger(), nullable=True),
            sa.Column('message_id', sa.BigInteger(), nullable=True),
            sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'ix_verification_sessions_guild_user', 'verification_sessions', ['guild_id', 'user_id'],
            unique=False,
        )

    audit_columns = {column['name'] for column in inspector.get_columns('audit_log_settings')}
    if 'verification' not in audit_columns:
        op.add_column(
            'audit_log_settings',
            sa.Column('verification', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        )

    # SQLAlchemy grava o NOME do membro do enum (VERIFICATION), nao o value.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_log_category ADD VALUE IF NOT EXISTS 'VERIFICATION'")


def downgrade() -> None:
    op.drop_column('audit_log_settings', 'verification')
    # Postgres nao suporta remover valor de enum (audit_log_category fica com 'VERIFICATION').

    op.drop_index('ix_verification_sessions_guild_user', table_name='verification_sessions')
    op.drop_table('verification_sessions')
    op.drop_table('verification_settings')

    op.execute('DROP TYPE IF EXISTS verification_session_status')
    op.execute('DROP TYPE IF EXISTS verification_method')
