"""metodo de avaliacao (ticket/dm/ambos) + customizacao da DM

Revision ID: b3d8f2a5c1e9
Revises: a7e3f1b9c4d2
Create Date: 2026-08-16 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d8f2a5c1e9'
down_revision: Union[str, None] = 'a7e3f1b9c4d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default garante que guildas ja existentes fiquem no
    # comportamento historico ("ticket") sem UPDATE separado.
    op.add_column(
        'evaluation_settings',
        sa.Column(
            'evaluation_method', sa.String(length=8), nullable=False, server_default='ticket'
        ),
    )
    op.add_column(
        'evaluation_settings', sa.Column('dm_embed_title', sa.String(length=256), nullable=True)
    )
    op.add_column(
        'evaluation_settings', sa.Column('dm_embed_description', sa.Text(), nullable=True)
    )
    op.add_column('evaluation_settings', sa.Column('dm_prompt_text', sa.Text(), nullable=True))
    op.add_column(
        'evaluation_settings', sa.Column('dm_button_label', sa.String(length=80), nullable=True)
    )
    op.add_column(
        'evaluation_settings', sa.Column('dm_thanks_message', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('evaluation_settings', 'dm_thanks_message')
    op.drop_column('evaluation_settings', 'dm_button_label')
    op.drop_column('evaluation_settings', 'dm_prompt_text')
    op.drop_column('evaluation_settings', 'dm_embed_description')
    op.drop_column('evaluation_settings', 'dm_embed_title')
    op.drop_column('evaluation_settings', 'evaluation_method')
