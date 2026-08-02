"""seed do comando /analises na central de ajuda (command_help)

Revision ID: e8a3c5f7b2d9
Revises: d2f6a8c1b4e7
Create Date: 2026-07-26 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e8a3c5f7b2d9'
down_revision: Union[str, None] = 'd2f6a8c1b4e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


command_help_table = sa.table(
    'command_help',
    sa.column('command_name', sa.String),
    sa.column('category', sa.String),
    sa.column('description', sa.Text),
    sa.column('usage', sa.String),
    sa.column('examples', postgresql.JSONB),
    sa.column('required_permission', sa.String),
    sa.column('enabled', sa.Boolean),
)


def upgrade() -> None:
    op.bulk_insert(
        command_help_table,
        [
            {
                'command_name': 'analises',
                'category': 'moderacao',
                'description': (
                    'Mostra o painel de punições atualmente em análise (isoladas, '
                    'aguardando recurso ou expiração do prazo).\n\n'
                    'Permite filtrar por tipo de punição e por staff responsável, e '
                    'aceitar/negar o recurso direto pelo painel.'
                ),
                'usage': '/analises filtro staff',
                'examples': ['/analises', '/analises filtro:ban', '/analises staff:@Carlos'],
                'required_permission': 'staff',
                'enabled': True,
            },
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM command_help WHERE command_name = 'analises'")
