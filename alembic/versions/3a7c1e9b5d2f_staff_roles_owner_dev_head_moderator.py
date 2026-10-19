"""substitui CEO por Head Moderator na hierarquia da staff

Revision ID: 3a7c1e9b5d2f
Revises: 2d6f9a1c8b44
Create Date: 2026-10-19 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "3a7c1e9b5d2f"
down_revision: Union[str, None] = "2d6f9a1c8b44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "guild_settings",
        "ceo_role_id",
        new_column_name="head_moderator_role_id",
    )


def downgrade() -> None:
    op.alter_column(
        "guild_settings",
        "head_moderator_role_id",
        new_column_name="ceo_role_id",
    )
