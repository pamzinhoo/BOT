"""botao opcional por painel de ticket

Permite desligar o botao clicavel de um painel especifico — usado quando o
painel serve so pra fornecer a embed principal de um combo ("Painel
Central"), sem ser ele mesmo uma categoria de ticket abrivel.

Revision ID: 7d3a9e1c4f68
Revises: 5255c5d14714
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d3a9e1c4f68'
down_revision: Union[str, Sequence[str], None] = '5255c5d14714'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("ticket_panels")}

    if "show_button" not in existing_columns:
        op.add_column(
            "ticket_panels",
            sa.Column("show_button", sa.Boolean(), server_default=sa.true(), nullable=False),
        )


def downgrade() -> None:
    op.drop_column("ticket_panels", "show_button")
