"""plan product link — vincula Plan ao catalogo generico de Products, base
pra concessao/revogacao automatica de License na aprovacao/expiracao de
assinatura

Revision ID: c2f5e8a1d4b7
Revises: a7d3f9c2b1e6
Create Date: 2026-08-06 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2f5e8a1d4b7'
down_revision: Union[str, None] = 'a7d3f9c2b1e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# idempotente de proposito, mesmo padrao de 6ff69141c9a6/a7d3f9c2b1e6.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("plans")}

    if "product_id" not in columns:
        op.add_column("plans", sa.Column("product_id", sa.UUID(), nullable=True))
        op.create_foreign_key(
            "fk_plans_product_id_products", "plans", "products", ["product_id"], ["id"], ondelete="SET NULL"
        )
        op.create_index("ix_plans_product_id", "plans", ["product_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_plans_product_id", table_name="plans")
    op.drop_constraint("fk_plans_product_id_products", "plans", type_="foreignkey")
    op.drop_column("plans", "product_id")
