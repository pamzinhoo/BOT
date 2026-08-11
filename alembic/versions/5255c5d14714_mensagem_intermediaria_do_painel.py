"""mensagem intermediaria configuravel do painel de ticket

Passo extra entre clicar no botao de categoria (Suporte/Denuncia/...) e abrir
o ticket de fato: quando `intro_enabled` liga, o clique mostra uma mensagem
efemera configuravel com um segundo botao (tambem personalizavel) que so ai
dispara formulario/criacao do ticket.

Revision ID: 5255c5d14714
Revises: c7d4a1e8f2b6
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5255c5d14714'
down_revision: Union[str, Sequence[str], None] = 'c7d4a1e8f2b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# idempotente de proposito: mesmo padrao das outras migrations deste arquivo,
# o pooler de transacao do Supabase pode nao manter tudo atomico.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("ticket_panels")}

    if "intro_enabled" not in existing_columns:
        op.add_column(
            "ticket_panels",
            sa.Column("intro_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        )
    if "intro_message" not in existing_columns:
        op.add_column("ticket_panels", sa.Column("intro_message", sa.Text(), nullable=True))
    if "intro_button_label" not in existing_columns:
        op.add_column(
            "ticket_panels", sa.Column("intro_button_label", sa.String(length=80), nullable=True)
        )
    if "intro_button_emoji" not in existing_columns:
        op.add_column(
            "ticket_panels", sa.Column("intro_button_emoji", sa.String(length=64), nullable=True)
        )
    if "intro_button_style" not in existing_columns:
        op.add_column(
            "ticket_panels",
            sa.Column(
                "intro_button_style",
                sa.String(length=16),
                server_default="primary",
                nullable=False,
            ),
        )


def downgrade() -> None:
    op.drop_column("ticket_panels", "intro_button_style")
    op.drop_column("ticket_panels", "intro_button_emoji")
    op.drop_column("ticket_panels", "intro_button_label")
    op.drop_column("ticket_panels", "intro_message")
    op.drop_column("ticket_panels", "intro_enabled")
