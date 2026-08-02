"""sistema de punicoes e recursos — punishments, punishment_appeals, config em guild_settings

Revision ID: f4a1c7e9b3d2
Revises: e1b6c9a4f2d3
Create Date: 2026-07-26 14:42:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f4a1c7e9b3d2'
down_revision: Union[str, None] = 'e1b6c9a4f2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('guild_settings', sa.Column('log_punishments_channel_id', sa.BigInteger(), nullable=True))
    op.add_column('guild_settings', sa.Column('appeal_channel_id', sa.BigInteger(), nullable=True))
    op.add_column('guild_settings', sa.Column('appeal_category_id', sa.BigInteger(), nullable=True))
    op.add_column('guild_settings', sa.Column('max_timeout_duration_minutes', sa.Integer(), nullable=True))
    op.add_column(
        'guild_settings',
        sa.Column('moderation_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )
    op.add_column(
        'guild_settings',
        sa.Column('require_proof', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )

    op.create_table(
        'punishments',
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('punishment_code', sa.String(length=20), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('user_name', sa.String(length=100), nullable=True),
        sa.Column('staff_id', sa.BigInteger(), nullable=False),
        sa.Column('staff_name', sa.String(length=100), nullable=True),
        sa.Column(
            'type',
            sa.Enum('BAN', 'BAN_TEMPORARIO', 'TIMEOUT', 'KICK', 'ADVERTENCIA', name='punishment_type'),
            nullable=False,
        ),
        sa.Column('reason', sa.String(length=1024), nullable=False),
        sa.Column('proofs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'status',
            sa.Enum('ACTIVE', 'EXPIRED', 'REVOKED', name='punishment_status'),
            nullable=False,
        ),
        sa.Column('dm_delivered', sa.Boolean(), nullable=False),
        sa.Column('revoked_by_id', sa.BigInteger(), nullable=True),
        sa.Column('revoked_by_name', sa.String(length=100), nullable=True),
        sa.Column('revoke_reason', sa.String(length=1024), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('punishment_code'),
    )
    op.create_index('ix_punishments_guild_id', 'punishments', ['guild_id'], unique=False)
    op.create_index('ix_punishments_user_id', 'punishments', ['user_id'], unique=False)

    op.create_table(
        'punishment_appeals',
        sa.Column('punishment_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('message', sa.String(length=2000), nullable=False),
        sa.Column('additional_info', sa.String(length=2000), nullable=True),
        sa.Column(
            'status',
            sa.Enum('PENDING', 'APPROVED', 'DENIED', name='appeal_status'),
            nullable=False,
        ),
        sa.Column('reviewed_by_id', sa.BigInteger(), nullable=True),
        sa.Column('reviewed_by_name', sa.String(length=100), nullable=True),
        sa.Column('review_reason', sa.String(length=1024), nullable=True),
        sa.Column('channel_message_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.ForeignKeyConstraint(['punishment_id'], ['punishments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_punishment_appeals_punishment_id', 'punishment_appeals', ['punishment_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_punishment_appeals_punishment_id', table_name='punishment_appeals')
    op.drop_table('punishment_appeals')
    op.execute('DROP TYPE IF EXISTS appeal_status')

    op.drop_index('ix_punishments_user_id', table_name='punishments')
    op.drop_index('ix_punishments_guild_id', table_name='punishments')
    op.drop_table('punishments')
    op.execute('DROP TYPE IF EXISTS punishment_status')
    op.execute('DROP TYPE IF EXISTS punishment_type')

    op.drop_column('guild_settings', 'require_proof')
    op.drop_column('guild_settings', 'moderation_enabled')
    op.drop_column('guild_settings', 'max_timeout_duration_minutes')
    op.drop_column('guild_settings', 'appeal_category_id')
    op.drop_column('guild_settings', 'appeal_channel_id')
    op.drop_column('guild_settings', 'log_punishments_channel_id')
