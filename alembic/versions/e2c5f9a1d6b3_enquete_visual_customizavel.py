"""enquete: imagem no embed + emoji/estilo de botao por opcao

Revision ID: e2c5f9a1d6b3
Revises: d3f8a4c6b1e5
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2c5f9a1d6b3'
down_revision: Union[str, None] = 'd3f8a4c6b1e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# idempotente de proposito, mesmo padrao das migrations anteriores.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    poll_columns = {c["name"] for c in inspector.get_columns("polls")}
    if "image_url" not in poll_columns:
        op.add_column("polls", sa.Column("image_url", sa.String(length=500), nullable=True))

    option_columns = {c["name"] for c in inspector.get_columns("poll_options")}
    if "emoji" not in option_columns:
        op.add_column("poll_options", sa.Column("emoji", sa.String(length=64), nullable=True))
    if "button_style" not in option_columns:
        op.add_column(
            "poll_options",
            sa.Column("button_style", sa.String(length=20), server_default="secondary", nullable=False),
        )


def downgrade() -> None:
    op.drop_column("poll_options", "button_style")
    op.drop_column("poll_options", "emoji")
    op.drop_column("polls", "image_url")
