"""sistema de renovacao de assinaturas — subscription_renewal_settings,
subscription_reminder_days, subscription_messages,
subscription_renewal_buttons, subscription_reminders + categoria de auditoria
SUBSCRIPTION

Revision ID: e7c3b1d9f4a6
Revises: f2b6d4a8c9e1
Create Date: 2026-07-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e7c3b1d9f4a6'
down_revision: Union[str, None] = 'f2b6d4a8c9e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENUMS = {
    'subscription_message_type': [
        'REMINDER', 'LAST_REMINDER', 'EXPIRED', 'RENEWED', 'GRACE_PERIOD',
    ],
    'subscription_renewal_button_key': ['RENEW', 'VIEW_PLAN', 'OPEN_STORE', 'CLOSE'],
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
                "SELECT typname FROM pg_type WHERE typname IN "
                "('subscription_message_type', 'subscription_renewal_button_key')"
            )
        )
    }

    for type_name, values in _ENUMS.items():
        if type_name not in existing_types:
            sa.Enum(*values, name=type_name).create(bind, checkfirst=False)

    message_type_enum = postgresql.ENUM(
        *_ENUMS['subscription_message_type'], name='subscription_message_type', create_type=False
    )
    button_key_enum = postgresql.ENUM(
        *_ENUMS['subscription_renewal_button_key'],
        name='subscription_renewal_button_key',
        create_type=False,
    )

    if 'subscription_renewal_settings' not in existing_tables:
        op.create_table(
            'subscription_renewal_settings',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('notify_via_dm', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('notify_via_channel', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('renewal_channel_id', sa.BigInteger(), nullable=True),
            sa.Column('grace_period_days', sa.Integer(), server_default=sa.text('0'), nullable=False),
            sa.Column('check_interval_hours', sa.Integer(), server_default=sa.text('24'), nullable=False),
            sa.Column('remove_roles_on_expire', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('remove_benefits_on_expire', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('end_subscription_on_expire', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('log_audit', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('send_dm_on_removal', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('continue_reminders_during_grace', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id'),
        )

    if 'subscription_reminder_days' not in existing_tables:
        op.create_table(
            'subscription_reminder_days',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('days_before', sa.Integer(), nullable=False),
            sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
            sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id', 'days_before', name='uq_subscription_reminder_day'),
        )
        op.create_index(
            'ix_subscription_reminder_days_guild_id',
            'subscription_reminder_days',
            ['guild_id'],
            unique=False,
        )

    if 'subscription_messages' not in existing_tables:
        op.create_table(
            'subscription_messages',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('message_type', message_type_enum, nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id', 'message_type', name='uq_subscription_message_type'),
        )
        op.create_index(
            'ix_subscription_messages_guild_id', 'subscription_messages', ['guild_id'], unique=False
        )

    if 'subscription_renewal_buttons' not in existing_tables:
        op.create_table(
            'subscription_renewal_buttons',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('key', button_key_enum, nullable=False),
            sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('label', sa.String(length=80), nullable=True),
            sa.Column('emoji', sa.String(length=64), nullable=True),
            sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id', 'key', name='uq_subscription_renewal_button_key'),
        )
        op.create_index(
            'ix_subscription_renewal_buttons_guild_id',
            'subscription_renewal_buttons',
            ['guild_id'],
            unique=False,
        )

    if 'subscription_reminders' not in existing_tables:
        op.create_table(
            'subscription_reminders',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('subscription_id', sa.UUID(), nullable=False),
            sa.Column('reminder_type', sa.String(length=50), nullable=False),
            sa.Column('period_end', sa.DateTime(timezone=True), nullable=True),
            sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('delivery_status', sa.String(length=20), server_default=sa.text("'sent'"), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint(
                'subscription_id', 'reminder_type', 'period_end',
                name='uq_subscription_reminder_once',
            ),
        )
        op.create_index(
            'ix_subscription_reminders_guild_id', 'subscription_reminders', ['guild_id'], unique=False
        )
        op.create_index(
            'ix_subscription_reminders_subscription_id',
            'subscription_reminders',
            ['subscription_id'],
            unique=False,
        )

    # toggle da nova categoria no painel de auditoria
    audit_columns = {column['name'] for column in inspector.get_columns('audit_log_settings')}
    if 'subscription' not in audit_columns:
        op.add_column(
            'audit_log_settings',
            sa.Column('subscription', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        )

    # nova categoria de auditoria — SQLAlchemy grava o NOME do membro do enum
    # (SUBSCRIPTION), nao o value ("subscription"); ver e5b7f3a9c2d4.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_log_category ADD VALUE IF NOT EXISTS 'SUBSCRIPTION'")


def downgrade() -> None:
    op.drop_column('audit_log_settings', 'subscription')

    op.drop_index('ix_subscription_reminders_subscription_id', table_name='subscription_reminders')
    op.drop_index('ix_subscription_reminders_guild_id', table_name='subscription_reminders')
    op.drop_table('subscription_reminders')

    op.drop_index(
        'ix_subscription_renewal_buttons_guild_id', table_name='subscription_renewal_buttons'
    )
    op.drop_table('subscription_renewal_buttons')

    op.drop_index('ix_subscription_messages_guild_id', table_name='subscription_messages')
    op.drop_table('subscription_messages')

    op.drop_index('ix_subscription_reminder_days_guild_id', table_name='subscription_reminder_days')
    op.drop_table('subscription_reminder_days')

    op.drop_table('subscription_renewal_settings')

    for type_name in _ENUMS:
        op.execute(f'DROP TYPE IF EXISTS {type_name}')
    # Postgres nao suporta remover valor de enum (audit_log_category.SUBSCRIPTION).
