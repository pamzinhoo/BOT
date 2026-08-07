"""sistema de licenciamento launcher — players, devices, launcher_sessions,
products, licenses, license_events, game_manifest_entries, downloads,
launcher_versions, launcher_news

Revision ID: 6ff69141c9a6
Revises: e6b2f8a4c1d9
Create Date: 2026-08-05 19:40:19.093591

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '6ff69141c9a6'
down_revision: Union[str, None] = 'e6b2f8a4c1d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENUMS = {
    'product_type': ['PERMANENT', 'SUBSCRIPTION', 'DLC', 'COSMETIC', 'DIGITAL_CONTENT'],
    'license_status': ['PENDING', 'ACTIVE', 'REVOKED', 'EXPIRED'],
    'license_event_type': ['CREATED', 'RENEWED', 'REVOKED', 'EXPIRED', 'REACTIVATED'],
    'manifest_entry_type': ['FULL', 'PATCH'],
    'download_status': ['AUTHORIZED', 'COMPLETED', 'FAILED', 'EXPIRED'],
    'launcher_platform': ['WINDOWS', 'MACOS', 'LINUX'],
}


# idempotente de proposito, mesmo padrao das migrations anteriores (ver
# c4f9a6e1b8d3): o pooler de transacao do Supabase pode nao manter a
# migration inteira atomica, entao cada CREATE checa o catalogo antes de
# rodar pra suportar reexecucao apos uma falha parcial sem limpeza manual.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    existing_types = {
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT typname FROM pg_type WHERE typname IN "
                "('product_type', 'license_status', 'license_event_type', "
                "'manifest_entry_type', 'download_status', 'launcher_platform')"
            )
        )
    }

    for type_name, values in _ENUMS.items():
        if type_name not in existing_types:
            sa.Enum(*values, name=type_name).create(bind, checkfirst=False)

    product_type_enum = postgresql.ENUM(*_ENUMS['product_type'], name='product_type', create_type=False)
    license_status_enum = postgresql.ENUM(*_ENUMS['license_status'], name='license_status', create_type=False)
    license_event_type_enum = postgresql.ENUM(
        *_ENUMS['license_event_type'], name='license_event_type', create_type=False
    )
    manifest_entry_type_enum = postgresql.ENUM(
        *_ENUMS['manifest_entry_type'], name='manifest_entry_type', create_type=False
    )
    download_status_enum = postgresql.ENUM(*_ENUMS['download_status'], name='download_status', create_type=False)
    launcher_platform_enum = postgresql.ENUM(
        *_ENUMS['launcher_platform'], name='launcher_platform', create_type=False
    )

    if 'players' not in existing_tables:
        op.create_table(
            'players',
            sa.Column('discord_id', sa.BigInteger(), nullable=False),
            sa.Column('discord_username', sa.String(length=64), nullable=True),
            sa.Column('linked_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_login_ip', postgresql.INET(), nullable=True),
            sa.Column('is_banned', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('banned_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('banned_reason', sa.String(length=200), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('discord_id'),
        )
        op.create_index('ix_players_discord_id', 'players', ['discord_id'], unique=True)

    if 'products' not in existing_tables:
        op.create_table(
            'products',
            sa.Column('slug', sa.String(length=80), nullable=False),
            sa.Column('name', sa.String(length=150), nullable=False),
            sa.Column('product_type', product_type_enum, nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('price_amount', sa.Integer(), nullable=True),
            sa.Column('currency', sa.String(length=8), server_default=sa.text("'BRL'"), nullable=False),
            sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
            sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('created_by_staff_id', sa.BigInteger(), nullable=True),
            sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('slug'),
        )

    if 'devices' not in existing_tables:
        op.create_table(
            'devices',
            sa.Column('player_id', sa.UUID(), nullable=False),
            sa.Column('device_uuid', sa.UUID(), nullable=False),
            sa.Column('label', sa.String(length=100), nullable=True),
            sa.Column('os_info', sa.String(length=200), nullable=True),
            sa.Column('launcher_version', sa.String(length=32), nullable=True),
            sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('last_ip', postgresql.INET(), nullable=True),
            sa.Column('revoked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('revoked_reason', sa.String(length=200), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('device_uuid'),
            sa.UniqueConstraint('player_id', 'device_uuid', name='uq_devices_player_uuid'),
        )
        op.create_index('ix_devices_player_id', 'devices', ['player_id'], unique=False)

    if 'launcher_sessions' not in existing_tables:
        op.create_table(
            'launcher_sessions',
            sa.Column('device_id', sa.UUID(), nullable=False),
            sa.Column('refresh_token_hash', sa.String(length=64), nullable=False),
            sa.Column('jwt_key_id', sa.String(length=32), nullable=True),
            sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_ip', postgresql.INET(), nullable=True),
            sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('revoked_reason', sa.String(length=200), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('refresh_token_hash'),
        )
        op.create_index('ix_launcher_sessions_device_id', 'launcher_sessions', ['device_id'], unique=False)
        op.create_index('ix_launcher_sessions_expires_at', 'launcher_sessions', ['expires_at'], unique=False)

    if 'licenses' not in existing_tables:
        op.create_table(
            'licenses',
            sa.Column('player_id', sa.UUID(), nullable=False),
            sa.Column('product_id', sa.UUID(), nullable=False),
            sa.Column('status', license_status_enum, server_default=sa.text("'PENDING'"), nullable=False),
            sa.Column('purchase_source', sa.String(length=50), nullable=False),
            sa.Column('external_reference', sa.String(length=200), nullable=True),
            sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('auto_renew', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('revoked_reason', sa.String(length=200), nullable=True),
            sa.Column('granted_by_staff_id', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='RESTRICT'),
            sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='RESTRICT'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('external_reference'),
            sa.UniqueConstraint('player_id', 'product_id', name='uq_licenses_player_product'),
        )
        op.create_index('ix_licenses_player_id', 'licenses', ['player_id'], unique=False)
        op.create_index('ix_licenses_product_id', 'licenses', ['product_id'], unique=False)
        op.create_index('ix_licenses_status', 'licenses', ['status'], unique=False)

    if 'license_events' not in existing_tables:
        op.create_table(
            'license_events',
            sa.Column('license_id', sa.UUID(), nullable=False),
            sa.Column('event_type', license_event_type_enum, nullable=False),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('event_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
            sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['license_id'], ['licenses.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_license_events_license_id', 'license_events', ['license_id'], unique=False)

    if 'game_manifest_entries' not in existing_tables:
        op.create_table(
            'game_manifest_entries',
            sa.Column('product_id', sa.UUID(), nullable=False),
            sa.Column('version', sa.String(length=32), nullable=False),
            sa.Column('sha256', sa.String(length=64), nullable=False),
            sa.Column('size_bytes', sa.BigInteger(), nullable=False),
            sa.Column('storage_path', sa.String(length=500), nullable=False),
            sa.Column('entry_type', manifest_entry_type_enum, server_default=sa.text("'FULL'"), nullable=False),
            sa.Column('depends_on', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
            sa.Column('is_current', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('release_notes', sa.Text(), nullable=True),
            sa.Column('created_by_staff_id', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.CheckConstraint('char_length(sha256) = 64', name='ck_manifest_sha256_length'),
            sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('product_id', 'version', 'entry_type', name='uq_manifest_product_version_type'),
        )
        op.create_index('ix_game_manifest_entries_product_id', 'game_manifest_entries', ['product_id'], unique=False)
        op.create_index('ix_game_manifest_entries_is_current', 'game_manifest_entries', ['is_current'], unique=False)

    if 'downloads' not in existing_tables:
        op.create_table(
            'downloads',
            sa.Column('player_id', sa.UUID(), nullable=True),
            sa.Column('device_id', sa.UUID(), nullable=True),
            sa.Column('product_id', sa.UUID(), nullable=False),
            sa.Column('manifest_entry_id', sa.UUID(), nullable=True),
            sa.Column('status', download_status_enum, server_default=sa.text("'AUTHORIZED'"), nullable=False),
            sa.Column('signed_url_issued_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('signed_url_expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('bytes_transferred', sa.BigInteger(), nullable=True),
            sa.Column('client_sha256', sa.String(length=64), nullable=True),
            sa.Column('ip_address', postgresql.INET(), nullable=True),
            sa.Column('failure_reason', sa.String(length=200), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='RESTRICT'),
            sa.ForeignKeyConstraint(['manifest_entry_id'], ['game_manifest_entries.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_downloads_player_id', 'downloads', ['player_id'], unique=False)
        op.create_index('ix_downloads_product_id', 'downloads', ['product_id'], unique=False)
        op.create_index('ix_downloads_status', 'downloads', ['status'], unique=False)

    if 'launcher_versions' not in existing_tables:
        op.create_table(
            'launcher_versions',
            sa.Column('version', sa.String(length=32), nullable=False),
            sa.Column('platform', launcher_platform_enum, nullable=False),
            sa.Column('sha256', sa.String(length=64), nullable=False),
            sa.Column('size_bytes', sa.BigInteger(), nullable=False),
            sa.Column('storage_path', sa.String(length=500), nullable=False),
            sa.Column('release_notes', sa.Text(), nullable=True),
            sa.Column('is_mandatory', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('is_current', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('published_by_staff_id', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.CheckConstraint('char_length(sha256) = 64', name='ck_launcher_versions_sha256_length'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('version', 'platform', name='uq_launcher_versions_version_platform'),
        )
        op.create_index('ix_launcher_versions_platform', 'launcher_versions', ['platform'], unique=False)

    if 'launcher_news' not in existing_tables:
        op.create_table(
            'launcher_news',
            sa.Column('title', sa.String(length=200), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('cover_image_url', sa.String(length=500), nullable=True),
            sa.Column('is_published', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_by_staff_id', sa.BigInteger(), nullable=True),
            sa.Column('published_by_staff_id', sa.BigInteger(), nullable=True),
            sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_launcher_news_is_published', 'launcher_news', ['is_published'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_launcher_news_is_published', table_name='launcher_news')
    op.drop_table('launcher_news')

    op.drop_index('ix_launcher_versions_platform', table_name='launcher_versions')
    op.drop_table('launcher_versions')

    op.drop_index('ix_downloads_status', table_name='downloads')
    op.drop_index('ix_downloads_product_id', table_name='downloads')
    op.drop_index('ix_downloads_player_id', table_name='downloads')
    op.drop_table('downloads')

    op.drop_index('ix_game_manifest_entries_is_current', table_name='game_manifest_entries')
    op.drop_index('ix_game_manifest_entries_product_id', table_name='game_manifest_entries')
    op.drop_table('game_manifest_entries')

    op.drop_index('ix_license_events_license_id', table_name='license_events')
    op.drop_table('license_events')

    op.drop_index('ix_licenses_status', table_name='licenses')
    op.drop_index('ix_licenses_product_id', table_name='licenses')
    op.drop_index('ix_licenses_player_id', table_name='licenses')
    op.drop_table('licenses')

    op.drop_index('ix_launcher_sessions_expires_at', table_name='launcher_sessions')
    op.drop_index('ix_launcher_sessions_device_id', table_name='launcher_sessions')
    op.drop_table('launcher_sessions')

    op.drop_index('ix_devices_player_id', table_name='devices')
    op.drop_table('devices')

    op.drop_table('products')

    op.drop_index('ix_players_discord_id', table_name='players')
    op.drop_table('players')

    for type_name in _ENUMS:
        op.execute(f'DROP TYPE IF EXISTS {type_name}')
