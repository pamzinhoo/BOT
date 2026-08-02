"""sistema de automod — automod_config, automod_settings, automod_logs

Revision ID: a3c7f1e9b2d4
Revises: e8a3c5f7b2d9
Create Date: 2026-07-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a3c7f1e9b2d4'
down_revision: Union[str, None] = 'e8a3c5f7b2d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# idempotente de proposito: o pooler de transacao do Supabase pode nao manter a
# migration inteira atomica (uma DDL fica commitada mesmo se a proxima falhar),
# entao cada CREATE checa o catalogo antes de rodar pra suportar reexecucao
# apos uma falha parcial sem precisar de limpeza manual no banco.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_types = {
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT typname FROM pg_type WHERE typname IN "
                "('automod_category', 'automod_risk_level')"
            )
        )
    }

    _CATEGORY_ENUM = postgresql.ENUM(
        'OFENSA', 'DISCRIMINACAO', 'GOLPE_SPAM', 'SEXUAL_ILEGAL', 'PRIVACIDADE',
        'AMEACA_ASSEDIO', 'SUSPEITA', 'PERSONALIZADA',
        name='automod_category', create_type=False,
    )
    _LEVEL_ENUM = postgresql.ENUM('BAIXO', 'MEDIO', 'ALTO', name='automod_risk_level', create_type=False)

    if 'automod_category' not in existing_types:
        sa.Enum(
            'OFENSA', 'DISCRIMINACAO', 'GOLPE_SPAM', 'SEXUAL_ILEGAL', 'PRIVACIDADE',
            'AMEACA_ASSEDIO', 'SUSPEITA', 'PERSONALIZADA',
            name='automod_category',
        ).create(bind, checkfirst=False)
    if 'automod_risk_level' not in existing_types:
        sa.Enum('BAIXO', 'MEDIO', 'ALTO', name='automod_risk_level').create(bind, checkfirst=False)

    existing_tables = set(inspector.get_table_names())

    if 'automod_config' not in existing_tables:
        op.create_table(
            'automod_config',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('palavra', sa.String(length=200), nullable=False),
            sa.Column('categoria', _CATEGORY_ENUM, nullable=False),
            sa.Column('nivel', _LEVEL_ENUM, nullable=False),
            sa.Column('is_builtin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('added_by_id', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_automod_config_guild_id', 'automod_config', ['guild_id'], unique=False)
        op.create_index(
            'ix_automod_config_guild_id_palavra', 'automod_config', ['guild_id', 'palavra'], unique=False
        )

    if 'automod_settings' not in existing_tables:
        op.create_table(
            'automod_settings',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('medio_timeout_minutes', sa.Integer(), server_default=sa.text('10'), nullable=False),
            sa.Column('alto_timeout_minutes', sa.Integer(), server_default=sa.text('1440'), nullable=False),
            sa.Column('alto_use_ban', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('alert_channel_id', sa.BigInteger(), nullable=True),
            sa.Column(
                'ignored_channel_ids', postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"), nullable=False,
            ),
            sa.Column(
                'ignored_role_ids', postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"), nullable=False,
            ),
            sa.Column(
                'allowed_words', postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"), nullable=False,
            ),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id'),
        )

    if 'automod_logs' not in existing_tables:
        op.create_table(
            'automod_logs',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('user_name', sa.String(length=100), nullable=True),
            sa.Column('channel_id', sa.BigInteger(), nullable=True),
            sa.Column('message_id', sa.BigInteger(), nullable=True),
            sa.Column('mensagem', sa.Text(), nullable=False),
            sa.Column('palavra_detectada', sa.String(length=200), nullable=False),
            sa.Column('categoria', _CATEGORY_ENUM, nullable=False),
            sa.Column('nivel', _LEVEL_ENUM, nullable=False),
            sa.Column('punicao_aplicada', sa.String(length=50), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_automod_logs_guild_id', 'automod_logs', ['guild_id'], unique=False)
        op.create_index('ix_automod_logs_user_id', 'automod_logs', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_automod_logs_user_id', table_name='automod_logs')
    op.drop_index('ix_automod_logs_guild_id', table_name='automod_logs')
    op.drop_table('automod_logs')

    op.drop_table('automod_settings')

    op.drop_index('ix_automod_config_guild_id_palavra', table_name='automod_config')
    op.drop_index('ix_automod_config_guild_id', table_name='automod_config')
    op.drop_table('automod_config')

    op.execute('DROP TYPE IF EXISTS automod_risk_level')
    op.execute('DROP TYPE IF EXISTS automod_category')
