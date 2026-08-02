"""central de ajuda dinamica — tabela command_help + seed dos comandos de moderacao

Revision ID: b1c8e4a9d3f5
Revises: a8e2d6f1c4b7
Create Date: 2026-07-26 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b1c8e4a9d3f5'
down_revision: Union[str, None] = 'a8e2d6f1c4b7'
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
    op.create_table(
        'command_help',
        sa.Column('command_name', sa.String(length=64), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('usage', sa.String(length=255), nullable=False),
        sa.Column('examples', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('required_permission', sa.String(length=16), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('command_name'),
    )

    op.bulk_insert(
        command_help_table,
        [
            {
                'command_name': 'punir',
                'category': 'moderacao',
                'description': (
                    'Aplica uma punição em um usuário.\n\n'
                    '**Tipos disponíveis:**\n'
                    '`ban` — Ban permanente\n'
                    '`ban_temporario` — Ban por tempo definido\n'
                    '`timeout` — Bloqueio temporário\n'
                    '`kick` — Expulsão\n'
                    '`advertencia` — Registro de advertência'
                ),
                'usage': '/punir usuário tipo motivo provas duração',
                'examples': [
                    '/punir @João timeout 30m Spam',
                    '/punir @Maria ban Divulgação proibida prova.png',
                ],
                'required_permission': 'staff',
                'enabled': True,
            },
            {
                'command_name': 'historico',
                'category': 'moderacao',
                'description': 'Mostra o histórico de punições de um membro.',
                'usage': '/historico usuário',
                'examples': ['/historico @João'],
                'required_permission': 'staff',
                'enabled': True,
            },
            {
                'command_name': 'recorrer',
                'category': 'moderacao',
                'description': 'Envia um recurso pra uma punição que você recebeu.',
                'usage': '/recorrer punicao motivo',
                'examples': ['/recorrer BAN-82931 Não fui eu quem enviou a mensagem'],
                'required_permission': 'public',
                'enabled': True,
            },
            {
                'command_name': 'revogar_punicao',
                'category': 'moderacao',
                'description': 'Revoga uma punição aplicada anteriormente (somente Owner).',
                'usage': '/revogar_punicao punicao motivo',
                'examples': ['/revogar_punicao BAN-82931 Recurso aceito manualmente'],
                'required_permission': 'admin',
                'enabled': True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table('command_help')
