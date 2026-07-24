"""config history — campos config_category/config_name/old_value/new_value em audit_log_entries

Revision ID: d2a7c4f8e1b9
Revises: d2a5c8f0e4b7
Create Date: 2026-07-24 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2a7c4f8e1b9'
down_revision: Union[str, None] = 'd2a5c8f0e4b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('audit_log_entries', sa.Column('config_category', sa.String(length=50), nullable=True))
    op.add_column('audit_log_entries', sa.Column('config_name', sa.String(length=100), nullable=True))
    op.add_column('audit_log_entries', sa.Column('old_value', sa.String(length=512), nullable=True))
    op.add_column('audit_log_entries', sa.Column('new_value', sa.String(length=512), nullable=True))
    op.create_index(
        'ix_audit_log_entries_config_name', 'audit_log_entries', ['config_name'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_audit_log_entries_config_name', table_name='audit_log_entries')
    op.drop_column('audit_log_entries', 'new_value')
    op.drop_column('audit_log_entries', 'old_value')
    op.drop_column('audit_log_entries', 'config_name')
    op.drop_column('audit_log_entries', 'config_category')
