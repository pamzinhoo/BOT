"""sistema de punicao pendente com isolamento temporario antes do ban definitivo

Revision ID: d7e4a2c1f9b8
Revises: c3f8b2a9d4e6
Create Date: 2026-07-26 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e4a2c1f9b8'
down_revision: Union[str, None] = 'c3f8b2a9d4e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE punishment_status ADD VALUE IF NOT EXISTS 'PENDING_REVIEW' BEFORE 'ACTIVE'"
        )
        op.execute("ALTER TYPE audit_log_category ADD VALUE IF NOT EXISTS 'punishment_review'")

    op.add_column('punishments', sa.Column('review_deadline_at', sa.DateTime(timezone=True), nullable=True))

    op.add_column('guild_settings', sa.Column('review_role_id', sa.BigInteger(), nullable=True))
    op.add_column('guild_settings', sa.Column('review_channel_id', sa.BigInteger(), nullable=True))
    op.add_column('guild_settings', sa.Column('review_timeout_minutes', sa.Integer(), nullable=True))

    op.add_column(
        'audit_log_settings',
        sa.Column('punishment_review', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )

    op.create_table(
        'punishment_review_roles',
        sa.Column('punishment_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('role_id', sa.BigInteger(), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.ForeignKeyConstraint(['punishment_id'], ['punishments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_punishment_review_roles_punishment_id',
        'punishment_review_roles', ['punishment_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_punishment_review_roles_punishment_id', table_name='punishment_review_roles')
    op.drop_table('punishment_review_roles')

    op.drop_column('audit_log_settings', 'punishment_review')

    op.drop_column('guild_settings', 'review_timeout_minutes')
    op.drop_column('guild_settings', 'review_channel_id')
    op.drop_column('guild_settings', 'review_role_id')

    op.drop_column('punishments', 'review_deadline_at')
    # Postgres nao suporta remover valor de enum — PENDING_REVIEW/punishment_review
    # ficam nos tipos `punishment_status`/`audit_log_category`.
