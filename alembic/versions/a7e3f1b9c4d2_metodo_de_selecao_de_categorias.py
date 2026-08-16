"""metodo de selecao das categorias de ticket (botoes | lista suspensa)

Revision ID: a7e3f1b9c4d2
Revises: 15cdb4300d1a
Create Date: 2026-08-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7e3f1b9c4d2'
down_revision: Union[str, None] = '15cdb4300d1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default garante que as linhas ja existentes fiquem no comportamento
    # historico ("buttons") sem precisar de UPDATE separado.
    op.add_column(
        'ticket_settings',
        sa.Column(
            'category_selection_mode',
            sa.String(length=16),
            nullable=False,
            server_default='buttons',
        ),
    )


def downgrade() -> None:
    op.drop_column('ticket_settings', 'category_selection_mode')
