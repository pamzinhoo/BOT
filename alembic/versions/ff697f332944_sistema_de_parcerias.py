"""sistema de parcerias — partnership_settings, partnerships

Revision ID: ff697f332944
Revises: b9c0ec638585
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff697f332944'
down_revision: Union[str, None] = 'b9c0ec638585'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# idempotente de proposito: o pooler de transacao do Supabase pode nao manter a
# migration inteira atomica (uma DDL fica commitada mesmo se a proxima falhar),
# entao cada CREATE checa o catalogo antes de rodar pra suportar reexecucao
# apos uma falha parcial sem precisar de limpeza manual no banco.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'partnership_settings' not in existing_tables:
        op.create_table(
            'partnership_settings',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('mode', sa.String(length=20), server_default='channel', nullable=False),
            sa.Column('category_channel_id', sa.BigInteger(), nullable=True),
            sa.Column('forum_channel_id', sa.BigInteger(), nullable=True),
            sa.Column('staff_role_id', sa.BigInteger(), nullable=True),
            sa.Column('cooldown_hours', sa.Integer(), server_default=sa.text('24'), nullable=False),
            sa.Column('allow_here', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('pre_message', sa.Text(), nullable=True),
            sa.Column('log_channel_id', sa.BigInteger(), nullable=True),
            sa.Column(
                'max_description_length', sa.Integer(), server_default=sa.text('500'), nullable=False
            ),
            sa.Column('allow_banner', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('allow_image', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('allow_invite', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column(
                'allow_external_links', sa.Boolean(), server_default=sa.text('true'), nullable=False
            ),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id'),
        )

    if 'partnerships' not in existing_tables:
        op.create_table(
            'partnerships',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('owner_id', sa.BigInteger(), nullable=False),
            sa.Column('role_id', sa.BigInteger(), nullable=True),
            sa.Column('channel_id', sa.BigInteger(), nullable=True),
            sa.Column('thread_id', sa.BigInteger(), nullable=True),
            sa.Column('message_id', sa.BigInteger(), nullable=True),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('invite', sa.String(length=200), nullable=True),
            sa.Column('banner', sa.String(length=500), nullable=True),
            sa.Column('category_label', sa.String(length=100), nullable=True),
            sa.Column('last_publish_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id', 'owner_id', name='uq_partnerships_guild_owner'),
        )
        op.create_index('ix_partnerships_guild_id', 'partnerships', ['guild_id'], unique=False)

    audit_columns = {column['name'] for column in inspector.get_columns('audit_log_settings')}
    if 'partnership' not in audit_columns:
        op.add_column(
            'audit_log_settings',
            sa.Column('partnership', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        )

    # SQLAlchemy grava o NOME do membro do enum (PARTNERSHIP), nao o value.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_log_category ADD VALUE IF NOT EXISTS 'PARTNERSHIP'")


def downgrade() -> None:
    op.drop_column('audit_log_settings', 'partnership')
    # Postgres nao suporta remover valor de enum (audit_log_category fica com 'PARTNERSHIP').

    op.drop_index('ix_partnerships_guild_id', table_name='partnerships')
    op.drop_table('partnerships')
    op.drop_table('partnership_settings')
