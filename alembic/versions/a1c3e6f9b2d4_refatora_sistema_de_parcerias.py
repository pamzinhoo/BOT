"""refatora sistema de parcerias — canal automatico, sem publish manual

Revision ID: a1c3e6f9b2d4
Revises: ff697f332944
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c3e6f9b2d4'
down_revision: Union[str, None] = 'ff697f332944'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# idempotente pelo mesmo motivo da migration anterior (pooler de transacao do
# Supabase pode nao manter tudo atomico): cada ALTER checa o catalogo antes.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    partnerships_columns = {column['name'] for column in inspector.get_columns('partnerships')}
    if 'last_publish_at' in partnerships_columns and 'last_announced_at' not in partnerships_columns:
        op.alter_column('partnerships', 'last_publish_at', new_column_name='last_announced_at')
        partnerships_columns.discard('last_publish_at')
        partnerships_columns.add('last_announced_at')

    if 'archived_at' not in partnerships_columns:
        op.add_column('partnerships', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))

    for obsolete_column in ('thread_id', 'message_id', 'name', 'description', 'invite', 'banner', 'category_label'):
        if obsolete_column in partnerships_columns:
            op.drop_column('partnerships', obsolete_column)

    settings_columns = {column['name'] for column in inspector.get_columns('partnership_settings')}
    if 'pre_message' in settings_columns and 'welcome_message' not in settings_columns:
        op.alter_column('partnership_settings', 'pre_message', new_column_name='welcome_message')
        settings_columns.discard('pre_message')
        settings_columns.add('welcome_message')

    new_settings_columns = [
        ('archive_category_id', sa.BigInteger(), None),
        ('auto_create', sa.Boolean(), sa.text('true')),
        ('auto_move', sa.Boolean(), sa.text('true')),
        ('role_removed_action', sa.String(length=20), "'archive'"),
        ('announcement_message', sa.Text(), None),
        ('announcement_channel_id', sa.BigInteger(), None),
        ('announcement_interval_minutes', sa.Integer(), sa.text('60')),
        ('mention_type', sa.String(length=20), "'none'"),
        ('last_announcement_at', sa.DateTime(timezone=True), None),
    ]
    for name, col_type, default in new_settings_columns:
        if name in settings_columns:
            continue
        nullable = default is None
        op.add_column(
            'partnership_settings',
            sa.Column(name, col_type, server_default=default, nullable=nullable),
        )

    for obsolete_column in (
        'mode', 'forum_channel_id', 'cooldown_hours', 'allow_here', 'max_description_length',
        'allow_banner', 'allow_image', 'allow_invite', 'allow_external_links',
    ):
        if obsolete_column in settings_columns:
            op.drop_column('partnership_settings', obsolete_column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    settings_columns = {column['name'] for column in inspector.get_columns('partnership_settings')}
    op.add_column('partnership_settings', sa.Column('mode', sa.String(length=20), server_default='channel', nullable=False))
    op.add_column('partnership_settings', sa.Column('forum_channel_id', sa.BigInteger(), nullable=True))
    op.add_column('partnership_settings', sa.Column('cooldown_hours', sa.Integer(), server_default=sa.text('24'), nullable=False))
    op.add_column('partnership_settings', sa.Column('allow_here', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('partnership_settings', sa.Column('max_description_length', sa.Integer(), server_default=sa.text('500'), nullable=False))
    op.add_column('partnership_settings', sa.Column('allow_banner', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('partnership_settings', sa.Column('allow_image', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('partnership_settings', sa.Column('allow_invite', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('partnership_settings', sa.Column('allow_external_links', sa.Boolean(), server_default=sa.text('true'), nullable=False))

    for name in (
        'archive_category_id', 'auto_create', 'auto_move', 'role_removed_action', 'announcement_message',
        'announcement_channel_id', 'announcement_interval_minutes', 'mention_type', 'last_announcement_at',
    ):
        if name in settings_columns:
            op.drop_column('partnership_settings', name)

    if 'welcome_message' in settings_columns:
        op.alter_column('partnership_settings', 'welcome_message', new_column_name='pre_message')

    partnerships_columns = {column['name'] for column in inspector.get_columns('partnerships')}
    op.add_column('partnerships', sa.Column('thread_id', sa.BigInteger(), nullable=True))
    op.add_column('partnerships', sa.Column('message_id', sa.BigInteger(), nullable=True))
    op.add_column('partnerships', sa.Column('name', sa.String(length=100), server_default='', nullable=False))
    op.add_column('partnerships', sa.Column('description', sa.Text(), server_default='', nullable=False))
    op.add_column('partnerships', sa.Column('invite', sa.String(length=200), nullable=True))
    op.add_column('partnerships', sa.Column('banner', sa.String(length=500), nullable=True))
    op.add_column('partnerships', sa.Column('category_label', sa.String(length=100), nullable=True))

    if 'archived_at' in partnerships_columns:
        op.drop_column('partnerships', 'archived_at')

    if 'last_announced_at' in partnerships_columns:
        op.alter_column('partnerships', 'last_announced_at', new_column_name='last_publish_at')
