"""adiciona colunas payment e enquete em audit_log_settings (toggles que faltavam
e quebravam audit_log_service.record() com AttributeError pras categorias PAYMENT
e ENQUETE — enquete ja existia no enum AuditLogCategory sem coluna correspondente)

Revision ID: c6f1a8d4e3b7
Revises: b5e9f3a7d2c4
Create Date: 2026-07-30 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6f1a8d4e3b7'
down_revision: Union[str, None] = 'b5e9f3a7d2c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'audit_log_settings',
        sa.Column('payment', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )
    op.add_column(
        'audit_log_settings',
        sa.Column('enquete', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('audit_log_settings', 'enquete')
    op.drop_column('audit_log_settings', 'payment')
