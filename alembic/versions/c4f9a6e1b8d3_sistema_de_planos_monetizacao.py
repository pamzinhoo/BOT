"""sistema de planos (monetizacao) — plans, plan_benefits, plan_messages,
subscriptions, subscription_history, payment_history, monetization_settings

Revision ID: c4f9a6e1b8d3
Revises: b7f4e2a9c1d8
Create Date: 2026-07-30 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c4f9a6e1b8d3'
down_revision: Union[str, None] = 'b7f4e2a9c1d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENUMS = {
    'plan_message_type': ['PURCHASE', 'RENEWAL', 'CANCELLATION', 'THANK_YOU', 'UPGRADE', 'DOWNGRADE'],
    'subscription_status': ['PENDING', 'ACTIVE', 'CANCELED', 'EXPIRED'],
    'subscription_billing_cycle': ['MONTHLY', 'YEARLY', 'ONE_TIME'],
    'subscription_event_type': ['CREATED', 'RENEWED', 'CANCELED', 'UPGRADED', 'DOWNGRADED', 'EXPIRED'],
    'payment_status': ['PENDING', 'APPROVED', 'REJECTED', 'REFUNDED'],
}


# idempotente de proposito: o pooler de transacao do Supabase pode nao manter a
# migration inteira atomica, entao cada CREATE checa o catalogo antes de rodar
# pra suportar reexecucao apos uma falha parcial sem precisar de limpeza manual.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    existing_types = {
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT typname FROM pg_type WHERE typname IN "
                "('plan_message_type', 'subscription_status', 'subscription_billing_cycle', "
                "'subscription_event_type', 'payment_status')"
            )
        )
    }

    for type_name, values in _ENUMS.items():
        if type_name not in existing_types:
            sa.Enum(*values, name=type_name).create(bind, checkfirst=False)

    message_type_enum = postgresql.ENUM(*_ENUMS['plan_message_type'], name='plan_message_type', create_type=False)
    status_enum = postgresql.ENUM(*_ENUMS['subscription_status'], name='subscription_status', create_type=False)
    cycle_enum = postgresql.ENUM(*_ENUMS['subscription_billing_cycle'], name='subscription_billing_cycle', create_type=False)
    event_enum = postgresql.ENUM(*_ENUMS['subscription_event_type'], name='subscription_event_type', create_type=False)
    payment_status_enum = postgresql.ENUM(*_ENUMS['payment_status'], name='payment_status', create_type=False)

    if 'plans' not in existing_tables:
        op.create_table(
            'plans',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('emoji', sa.String(length=64), nullable=True),
            sa.Column('color', sa.Integer(), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('price_monthly', sa.Integer(), nullable=True),
            sa.Column('price_yearly', sa.Integer(), nullable=True),
            sa.Column('price_one_time', sa.Integer(), nullable=True),
            sa.Column('currency', sa.String(length=8), server_default=sa.text("'BRL'"), nullable=False),
            sa.Column('role_id', sa.BigInteger(), nullable=True),
            sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
            sa.Column('is_recommended', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id', 'name', name='uq_plans_guild_name'),
        )
        op.create_index('ix_plans_guild_id', 'plans', ['guild_id'], unique=False)

    if 'plan_benefits' not in existing_tables:
        op.create_table(
            'plan_benefits',
            sa.Column('plan_id', sa.UUID(), nullable=False),
            sa.Column('text', sa.String(length=200), nullable=False),
            sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_plan_benefits_plan_id', 'plan_benefits', ['plan_id'], unique=False)

    if 'plan_messages' not in existing_tables:
        op.create_table(
            'plan_messages',
            sa.Column('plan_id', sa.UUID(), nullable=False),
            sa.Column('message_type', message_type_enum, nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('plan_id', 'message_type', name='uq_plan_message_type'),
        )

    if 'subscriptions' not in existing_tables:
        op.create_table(
            'subscriptions',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('plan_id', sa.UUID(), nullable=False),
            sa.Column('status', status_enum, server_default=sa.text("'PENDING'"), nullable=False),
            sa.Column('billing_cycle', cycle_enum, nullable=False),
            sa.Column('provider', sa.String(length=50), nullable=False),
            sa.Column('external_reference', sa.String(length=200), nullable=True),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
            sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ondelete='RESTRICT'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id', 'user_id', 'plan_id', name='uq_subscription_guild_user_plan'),
            sa.UniqueConstraint('external_reference'),
        )
        op.create_index('ix_subscriptions_guild_id', 'subscriptions', ['guild_id'], unique=False)
        op.create_index('ix_subscriptions_user_id', 'subscriptions', ['user_id'], unique=False)

    if 'subscription_history' not in existing_tables:
        op.create_table(
            'subscription_history',
            sa.Column('subscription_id', sa.UUID(), nullable=False),
            sa.Column('event_type', event_enum, nullable=False),
            sa.Column('from_plan_id', sa.UUID(), nullable=True),
            sa.Column('to_plan_id', sa.UUID(), nullable=True),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['from_plan_id'], ['plans.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['to_plan_id'], ['plans.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'ix_subscription_history_subscription_id', 'subscription_history', ['subscription_id'], unique=False
        )

    if 'payment_history' not in existing_tables:
        op.create_table(
            'payment_history',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('plan_id', sa.UUID(), nullable=False),
            sa.Column('subscription_id', sa.UUID(), nullable=True),
            sa.Column('provider', sa.String(length=50), nullable=False),
            sa.Column('external_id', sa.String(length=200), nullable=False),
            sa.Column('amount', sa.Integer(), nullable=False),
            sa.Column('currency', sa.String(length=8), server_default=sa.text("'BRL'"), nullable=False),
            sa.Column('status', payment_status_enum, server_default=sa.text("'PENDING'"), nullable=False),
            sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ondelete='RESTRICT'),
            sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('provider', 'external_id', name='uq_payment_provider_external_id'),
        )
        op.create_index('ix_payment_history_guild_id', 'payment_history', ['guild_id'], unique=False)
        op.create_index('ix_payment_history_user_id', 'payment_history', ['user_id'], unique=False)

    if 'monetization_settings' not in existing_tables:
        op.create_table(
            'monetization_settings',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('shop_channel_id', sa.BigInteger(), nullable=True),
            sa.Column('approval_channel_id', sa.BigInteger(), nullable=True),
            sa.Column('log_channel_id', sa.BigInteger(), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id'),
        )


def downgrade() -> None:
    op.drop_table('monetization_settings')

    op.drop_index('ix_payment_history_user_id', table_name='payment_history')
    op.drop_index('ix_payment_history_guild_id', table_name='payment_history')
    op.drop_table('payment_history')

    op.drop_index('ix_subscription_history_subscription_id', table_name='subscription_history')
    op.drop_table('subscription_history')

    op.drop_index('ix_subscriptions_user_id', table_name='subscriptions')
    op.drop_index('ix_subscriptions_guild_id', table_name='subscriptions')
    op.drop_table('subscriptions')

    op.drop_table('plan_messages')

    op.drop_index('ix_plan_benefits_plan_id', table_name='plan_benefits')
    op.drop_table('plan_benefits')

    op.drop_index('ix_plans_guild_id', table_name='plans')
    op.drop_table('plans')

    for type_name in _ENUMS:
        op.execute(f'DROP TYPE IF EXISTS {type_name}')
