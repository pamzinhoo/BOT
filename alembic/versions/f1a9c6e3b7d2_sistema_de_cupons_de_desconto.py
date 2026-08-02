"""sistema de cupons de desconto — discount_coupons, discount_coupon_plans,
discount_coupon_redemptions + categoria de auditoria COUPON

Revision ID: f1a9c6e3b7d2
Revises: e7c3b1d9f4a6
Create Date: 2026-07-31 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f1a9c6e3b7d2'
down_revision: Union[str, None] = 'e7c3b1d9f4a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DISCOUNT_TYPE_VALUES = ['PERCENTAGE', 'FIXED']


# idempotente de proposito, mesma tecnica de e7c3b1d9f4a6: o pooler de
# transacao do Supabase pode nao manter a migration inteira atomica, entao
# cada CREATE checa o catalogo antes de rodar.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    existing_types = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT typname FROM pg_type WHERE typname = 'discount_coupon_type'")
        )
    }

    if 'discount_coupon_type' not in existing_types:
        sa.Enum(*_DISCOUNT_TYPE_VALUES, name='discount_coupon_type').create(bind, checkfirst=False)

    discount_type_enum = postgresql.ENUM(
        *_DISCOUNT_TYPE_VALUES, name='discount_coupon_type', create_type=False
    )

    if 'discount_coupons' not in existing_tables:
        op.create_table(
            'discount_coupons',
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('code', sa.String(length=64), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('emoji', sa.String(length=64), nullable=True),
            sa.Column('discount_type', discount_type_enum, nullable=False),
            sa.Column('discount_value', sa.Integer(), server_default=sa.text('0'), nullable=False),
            sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('max_global_uses', sa.Integer(), nullable=True),
            sa.Column('max_uses_per_user', sa.Integer(), nullable=True),
            sa.Column('required_role_id', sa.BigInteger(), nullable=True),
            sa.Column('allow_stack', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column(
                'billing_cycles',
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=False,
            ),
            sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('guild_id', 'code', name='uq_discount_coupons_guild_code'),
        )
        op.create_index(
            'ix_discount_coupons_guild_id', 'discount_coupons', ['guild_id'], unique=False
        )

    # 0 linhas para um cupom = "vale pra todos os planos" (sem sentinela).
    if 'discount_coupon_plans' not in existing_tables:
        op.create_table(
            'discount_coupon_plans',
            sa.Column('coupon_id', sa.UUID(), nullable=False),
            sa.Column('plan_id', sa.UUID(), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['coupon_id'], ['discount_coupons.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('coupon_id', 'plan_id', name='uq_discount_coupon_plan'),
        )
        op.create_index(
            'ix_discount_coupon_plans_coupon_id', 'discount_coupon_plans', ['coupon_id'], unique=False
        )
        op.create_index(
            'ix_discount_coupon_plans_plan_id', 'discount_coupon_plans', ['plan_id'], unique=False
        )

    # FK RESTRICT de proposito: historico de uso nunca some junto com o cupom.
    if 'discount_coupon_redemptions' not in existing_tables:
        op.create_table(
            'discount_coupon_redemptions',
            sa.Column('coupon_id', sa.UUID(), nullable=False),
            sa.Column('guild_id', sa.BigInteger(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('payment_id', sa.UUID(), nullable=True),
            sa.Column('original_price', sa.Integer(), nullable=False),
            sa.Column('discount_amount', sa.Integer(), nullable=False),
            sa.Column('final_price', sa.Integer(), nullable=False),
            sa.Column('redeemed_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.ForeignKeyConstraint(['coupon_id'], ['discount_coupons.id'], ondelete='RESTRICT'),
            sa.ForeignKeyConstraint(['payment_id'], ['payment_history.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'ix_discount_coupon_redemptions_coupon_id',
            'discount_coupon_redemptions',
            ['coupon_id'],
            unique=False,
        )
        op.create_index(
            'ix_discount_coupon_redemptions_guild_id',
            'discount_coupon_redemptions',
            ['guild_id'],
            unique=False,
        )
        op.create_index(
            'ix_discount_coupon_redemptions_user_id',
            'discount_coupon_redemptions',
            ['user_id'],
            unique=False,
        )

    # toggle da nova categoria no painel de auditoria
    audit_columns = {column['name'] for column in inspector.get_columns('audit_log_settings')}
    if 'coupon' not in audit_columns:
        op.add_column(
            'audit_log_settings',
            sa.Column('coupon', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        )

    # nova categoria de auditoria — SQLAlchemy grava o NOME do membro do enum
    # (COUPON), nao o value ("coupon"); ver e5b7f3a9c2d4.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_log_category ADD VALUE IF NOT EXISTS 'COUPON'")


def downgrade() -> None:
    op.drop_column('audit_log_settings', 'coupon')

    op.drop_index(
        'ix_discount_coupon_redemptions_user_id', table_name='discount_coupon_redemptions'
    )
    op.drop_index(
        'ix_discount_coupon_redemptions_guild_id', table_name='discount_coupon_redemptions'
    )
    op.drop_index(
        'ix_discount_coupon_redemptions_coupon_id', table_name='discount_coupon_redemptions'
    )
    op.drop_table('discount_coupon_redemptions')

    op.drop_index('ix_discount_coupon_plans_plan_id', table_name='discount_coupon_plans')
    op.drop_index('ix_discount_coupon_plans_coupon_id', table_name='discount_coupon_plans')
    op.drop_table('discount_coupon_plans')

    op.drop_index('ix_discount_coupons_guild_id', table_name='discount_coupons')
    op.drop_table('discount_coupons')

    op.execute('DROP TYPE IF EXISTS discount_coupon_type')
    # Postgres nao suporta remover valor de enum (audit_log_category.COUPON).
