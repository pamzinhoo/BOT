"""audit logs — audit_log_settings e audit_log_entries

Revision ID: c9f4a3e7b1d6
Revises: b4e1f9a2c7d3
Create Date: 2026-07-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c9f4a3e7b1d6'
down_revision: Union[str, None] = 'b4e1f9a2c7d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'audit_log_settings',
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('channel_id', sa.BigInteger(), nullable=True),
        sa.Column('ban', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('kick', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('timeout', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('role_update', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('nickname', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('channel_update', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('category_update', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('permission_update', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('channel_create_delete', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('role_create_delete', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('message_delete', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('message_edit', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('bulk_delete', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('voice_join_leave', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('voice_move', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('mute_unmute', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('deaf_undeaf', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('bot_added', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('emoji', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('sticker', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('server_config', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('tickets', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id'),
    )
    op.create_table(
        'audit_log_entries',
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column(
            'category',
            sa.Enum(
                'BAN', 'KICK', 'TIMEOUT', 'ROLE_UPDATE', 'NICKNAME', 'CHANNEL_UPDATE',
                'CATEGORY_UPDATE', 'PERMISSION_UPDATE', 'CHANNEL_CREATE_DELETE',
                'ROLE_CREATE_DELETE', 'MESSAGE_DELETE', 'MESSAGE_EDIT', 'BULK_DELETE',
                'VOICE_JOIN_LEAVE', 'VOICE_MOVE', 'MUTE_UNMUTE', 'DEAF_UNDEAF', 'BOT_ADDED',
                'EMOJI', 'STICKER', 'SERVER_CONFIG', 'TICKETS',
                name='audit_log_category',
            ),
            nullable=False,
        ),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('executor_id', sa.BigInteger(), nullable=True),
        sa.Column('executor_name', sa.String(length=100), nullable=True),
        sa.Column('target_id', sa.BigInteger(), nullable=True),
        sa.Column('target_name', sa.String(length=100), nullable=True),
        sa.Column('reason', sa.String(length=512), nullable=True),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_audit_log_entries_guild_id', 'audit_log_entries', ['guild_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_audit_log_entries_guild_id', table_name='audit_log_entries')
    op.drop_table('audit_log_entries')
    op.drop_table('audit_log_settings')
    op.execute('DROP TYPE IF EXISTS audit_log_category')
