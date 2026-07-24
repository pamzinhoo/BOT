"""central de configuracao fase 1 — settings por dominio + cargos novos

Revision ID: d2a5c8f0e4b7
Revises: c9f4a3e7b1d6
Create Date: 2026-07-24 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd2a5c8f0e4b7'
down_revision: Union[str, None] = 'c9f4a3e7b1d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('guild_settings', sa.Column('owner_role_id', sa.BigInteger(), nullable=True))
    op.add_column('guild_settings', sa.Column('support_role_id', sa.BigInteger(), nullable=True))
    op.add_column('guild_settings', sa.Column('partner_role_id', sa.BigInteger(), nullable=True))
    op.add_column('guild_settings', sa.Column('streamer_role_id', sa.BigInteger(), nullable=True))

    op.create_table(
        'ticket_settings',
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('max_tickets_per_user', sa.Integer(), nullable=True),
        sa.Column('allow_multiple_tickets', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('auto_close_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('delete_delay_seconds', sa.Integer(), server_default=sa.text('10'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id'),
    )

    op.create_table(
        'evaluation_settings',
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('min_comment_rating', sa.Integer(), server_default=sa.text('2'), nullable=True),
        sa.Column('star_emoji', sa.String(length=20), server_default='⭐', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id'),
    )

    op.create_table(
        'dashboard_settings',
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('auto_update_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('update_interval_minutes', sa.Integer(), server_default=sa.text('15'), nullable=False),
        sa.Column('top_count', sa.Integer(), server_default=sa.text('5'), nullable=False),
        sa.Column('show_chart', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id'),
    )

    op.create_table(
        'ranking_settings',
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('criteria', sa.String(length=20), server_default='tickets', nullable=False),
        sa.Column('default_period', sa.String(length=20), server_default='alltime', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id'),
    )

    op.create_table(
        'anti_spam_settings',
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('window_seconds', sa.Integer(), server_default=sa.text('60'), nullable=False),
        sa.Column('cross_channel_threshold', sa.Integer(), server_default=sa.text('3'), nullable=False),
        sa.Column('flood_window_seconds', sa.Integer(), server_default=sa.text('15'), nullable=False),
        sa.Column('flood_threshold', sa.Integer(), server_default=sa.text('4'), nullable=False),
        sa.Column('repeat_threshold', sa.Integer(), server_default=sa.text('3'), nullable=False),
        sa.Column('ignore_staff', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('default_action', sa.String(length=20), server_default='alerta', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id'),
    )

    op.create_table(
        'permission_settings',
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('claim', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('unclaim', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('fechar', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('reabrir', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('excluir', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('auditoria', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('ranking', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id'),
    )


def downgrade() -> None:
    op.drop_table('permission_settings')
    op.drop_table('anti_spam_settings')
    op.drop_table('ranking_settings')
    op.drop_table('dashboard_settings')
    op.drop_table('evaluation_settings')
    op.drop_table('ticket_settings')
    op.drop_column('guild_settings', 'streamer_role_id')
    op.drop_column('guild_settings', 'partner_role_id')
    op.drop_column('guild_settings', 'support_role_id')
    op.drop_column('guild_settings', 'owner_role_id')
