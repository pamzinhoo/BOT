"""seed command_help — /assinatura ver e /assinatura cancelar

Revision ID: e9c3b7a1d5f2
Revises: d7a2c9e5f1b8
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'e9c3b7a1d5f2'
down_revision: Union[str, None] = 'd7a2c9e5f1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

command_help_table = sa.table(
    'command_help',
    sa.column('command_name', sa.String),
    sa.column('category', sa.String),
    sa.column('description', sa.Text),
    sa.column('usage', sa.String),
    sa.column('examples', JSONB),
    sa.column('required_permission', sa.String),
    sa.column('enabled', sa.Boolean),
)


def upgrade() -> None:
    op.bulk_insert(
        command_help_table,
        [
            {
                'command_name': 'assinatura ver',
                'category': 'monetizacao',
                'description': 'Mostra suas assinaturas ativas de Planos neste servidor.',
                'usage': '/assinatura ver',
                'examples': ['/assinatura ver'],
                'required_permission': 'public',
                'enabled': True,
            },
            {
                'command_name': 'assinatura cancelar',
                'category': 'monetizacao',
                'description': (
                    'Cancela a(s) assinatura(s) (ativa ou pendente) de um usuário neste '
                    'servidor. Remove o cargo do plano quando aplicável e registra no log '
                    'de monetização — histórico financeiro nunca é apagado.'
                ),
                'usage': '/assinatura cancelar usuario',
                'examples': ['/assinatura cancelar usuario:@Nome'],
                'required_permission': 'admin',
                'enabled': True,
            },
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM command_help WHERE command_name IN ('assinatura ver', 'assinatura cancelar')")
