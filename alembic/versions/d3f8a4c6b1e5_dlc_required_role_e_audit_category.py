"""dlc: cargo obrigatorio (DLC gratuita) em Product + categoria PRODUCT no
audit log

Revision ID: d3f8a4c6b1e5
Revises: b3d8f2a5c1e9
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3f8a4c6b1e5'
down_revision: Union[str, None] = 'b3d8f2a5c1e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# idempotente de proposito, mesmo padrao de c2f5e8a1d4b7/f4a1c8d5e2b6.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    product_columns = {c["name"] for c in inspector.get_columns("products")}
    if "required_role_id" not in product_columns:
        op.add_column("products", sa.Column("required_role_id", sa.BigInteger(), nullable=True))
    if "required_role_guild_id" not in product_columns:
        op.add_column("products", sa.Column("required_role_guild_id", sa.BigInteger(), nullable=True))

    audit_columns = {c["name"] for c in inspector.get_columns("audit_log_settings")}
    if "product" not in audit_columns:
        op.add_column(
            "audit_log_settings",
            sa.Column("product", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        )

    # SQLAlchemy grava o NOME do membro do enum (PRODUCT), nao o value ("product").
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_log_category ADD VALUE IF NOT EXISTS 'PRODUCT'")


def downgrade() -> None:
    op.drop_column("audit_log_settings", "product")
    op.drop_column("products", "required_role_guild_id")
    op.drop_column("products", "required_role_id")
    # Postgres nao suporta remover valor de enum.
