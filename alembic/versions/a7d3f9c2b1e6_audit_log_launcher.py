"""audit log launcher — auditoria global do fluxo de login do Launcher

Revision ID: a7d3f9c2b1e6
Revises: 6ff69141c9a6
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7d3f9c2b1e6'
down_revision: Union[str, None] = '6ff69141c9a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACTION_VALUES = [
    'LOGIN_SUCCESS',
    'LOGIN_FAILED',
    'REFRESH_ROTATED',
    'REFRESH_REUSE_DETECTED',
    'LOGOUT',
    'LOGOUT_ALL',
    'DEVICE_REVOKED',
    'RATE_LIMITED',
]


# idempotente de proposito, mesmo padrao de 6ff69141c9a6.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    existing_types = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT typname FROM pg_type WHERE typname = 'audit_log_launcher_action'")
        )
    }

    if 'audit_log_launcher_action' not in existing_types:
        sa.Enum(*_ACTION_VALUES, name='audit_log_launcher_action').create(bind, checkfirst=False)

    action_enum = postgresql.ENUM(
        *_ACTION_VALUES, name='audit_log_launcher_action', create_type=False
    )

    if 'audit_log_launcher' not in existing_tables:
        op.create_table(
            'audit_log_launcher',
            sa.Column('player_id', sa.UUID(), nullable=True),
            sa.Column('device_id', sa.UUID(), nullable=True),
            sa.Column('action', action_enum, nullable=False),
            sa.Column('ip_address', postgresql.INET(), nullable=True),
            sa.Column('audit_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_audit_log_launcher_player_id', 'audit_log_launcher', ['player_id'], unique=False)
        op.create_index('ix_audit_log_launcher_device_id', 'audit_log_launcher', ['device_id'], unique=False)
        op.create_index('ix_audit_log_launcher_action', 'audit_log_launcher', ['action'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_audit_log_launcher_action', table_name='audit_log_launcher')
    op.drop_index('ix_audit_log_launcher_device_id', table_name='audit_log_launcher')
    op.drop_index('ix_audit_log_launcher_player_id', table_name='audit_log_launcher')
    op.drop_table('audit_log_launcher')
    op.execute('DROP TYPE IF EXISTS audit_log_launcher_action')
