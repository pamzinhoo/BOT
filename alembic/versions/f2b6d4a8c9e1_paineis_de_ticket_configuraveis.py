"""paineis de ticket configuraveis — ticket_panels, ticket_panel_form_fields,
ticket_form_responses, ticket_settings.enabled e as colunas de painel/aprovacao
em tickets

Revision ID: f2b6d4a8c9e1
Revises: e9c3b7a1d5f2
Create Date: 2026-07-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f2b6d4a8c9e1'
down_revision: Union[str, None] = 'e9c3b7a1d5f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# SQLAlchemy grava o NOME do membro do enum (NONE/PENDING/...), nao o value —
# e isso que precisa existir no tipo do Postgres (mesma pegadinha de b4e7f2a8c3d6).
_APPROVAL_STATUS = ['NONE', 'PENDING', 'APPROVED', 'REPROVED']


# idempotente de proposito: o pooler de transacao do Supabase pode nao manter a
# migration inteira atomica, entao cada CREATE/ADD checa o catalogo antes de rodar.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'ticket_panels' not in existing_tables:
        op.create_table(
            'ticket_panels',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('key', sa.String(length=64), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('channel_id', sa.BigInteger(), nullable=True),
            sa.Column('message_id', sa.BigInteger(), nullable=True),
            sa.Column('ticket_category_id', sa.BigInteger(), nullable=True),
            sa.Column('responsible_role_ids', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
            sa.Column('embed_title', sa.String(length=256), nullable=True),
            sa.Column('embed_description', sa.Text(), nullable=True),
            sa.Column('embed_color', sa.Integer(), nullable=True),
            sa.Column('embed_image_url', sa.Text(), nullable=True),
            sa.Column('embed_thumbnail_url', sa.Text(), nullable=True),
            sa.Column('embed_footer', sa.Text(), nullable=True),
            sa.Column('button_label', sa.String(length=80), nullable=True),
            sa.Column('button_emoji', sa.String(length=64), nullable=True),
            sa.Column('button_style', sa.String(length=16), server_default=sa.text("'primary'"), nullable=False),
            sa.Column('max_tickets_per_user', sa.Integer(), nullable=True),
            sa.Column('allow_multiple_tickets', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('auto_close_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('delete_delay_seconds', sa.Integer(), server_default=sa.text('10'), nullable=False),
            sa.Column('transcript_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('evaluation_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('dm_on_close_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('claim_role_ids', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
            sa.Column('form_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('approval_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('approval_granted_role_id', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id', 'key', name='uq_ticket_panels_guild_key'),
        )
        op.create_index('ix_ticket_panels_guild_id', 'ticket_panels', ['guild_id'], unique=False)

    if 'ticket_panel_form_fields' not in existing_tables:
        op.create_table(
            'ticket_panel_form_fields',
            sa.Column('panel_id', sa.UUID(), nullable=False),
            sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
            sa.Column('label', sa.String(length=45), nullable=False),
            sa.Column('style', sa.String(length=16), server_default=sa.text("'short'"), nullable=False),
            sa.Column('required', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('placeholder', sa.String(length=100), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['panel_id'], ['ticket_panels.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'ix_ticket_panel_form_fields_panel_id', 'ticket_panel_form_fields', ['panel_id'], unique=False
        )

    if 'ticket_form_responses' not in existing_tables:
        op.create_table(
            'ticket_form_responses',
            sa.Column('ticket_id', sa.UUID(), nullable=False),
            sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
            sa.Column('field_label', sa.String(length=45), nullable=False),
            sa.Column('answer_text', sa.Text(), server_default=sa.text("''"), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'ix_ticket_form_responses_ticket_id', 'ticket_form_responses', ['ticket_id'], unique=False
        )

    # kill switch global do sistema de tickets
    ticket_settings_columns = {c['name'] for c in inspector.get_columns('ticket_settings')}
    if 'enabled' not in ticket_settings_columns:
        op.add_column(
            'ticket_settings',
            sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        )

    # vinculo do ticket com o painel + etapa opcional de aprovacao
    existing_types = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT typname FROM pg_type WHERE typname = 'ticket_approval_status'")
        )
    }
    if 'ticket_approval_status' not in existing_types:
        sa.Enum(*_APPROVAL_STATUS, name='ticket_approval_status').create(bind, checkfirst=False)
    approval_enum = postgresql.ENUM(
        *_APPROVAL_STATUS, name='ticket_approval_status', create_type=False
    )

    tickets_columns = {c['name'] for c in inspector.get_columns('tickets')}
    if 'panel_id' not in tickets_columns:
        op.add_column('tickets', sa.Column('panel_id', sa.UUID(), nullable=True))
        op.create_foreign_key(
            'fk_tickets_panel_id', 'tickets', 'ticket_panels', ['panel_id'], ['id'], ondelete='SET NULL'
        )
    if 'approval_status' not in tickets_columns:
        op.add_column(
            'tickets',
            sa.Column(
                'approval_status', approval_enum, server_default=sa.text("'NONE'"), nullable=False
            ),
        )
    if 'approval_reviewed_by' not in tickets_columns:
        op.add_column('tickets', sa.Column('approval_reviewed_by', sa.BigInteger(), nullable=True))
    if 'approval_reviewed_at' not in tickets_columns:
        op.add_column(
            'tickets', sa.Column('approval_reviewed_at', sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    op.drop_column('tickets', 'approval_reviewed_at')
    op.drop_column('tickets', 'approval_reviewed_by')
    op.drop_column('tickets', 'approval_status')
    op.drop_constraint('fk_tickets_panel_id', 'tickets', type_='foreignkey')
    op.drop_column('tickets', 'panel_id')
    op.execute('DROP TYPE IF EXISTS ticket_approval_status')

    op.drop_column('ticket_settings', 'enabled')

    op.drop_index('ix_ticket_form_responses_ticket_id', table_name='ticket_form_responses')
    op.drop_table('ticket_form_responses')

    op.drop_index('ix_ticket_panel_form_fields_panel_id', table_name='ticket_panel_form_fields')
    op.drop_table('ticket_panel_form_fields')

    op.drop_index('ix_ticket_panels_guild_id', table_name='ticket_panels')
    op.drop_table('ticket_panels')
