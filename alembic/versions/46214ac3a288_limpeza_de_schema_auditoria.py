"""limpeza de schema (auditoria) — indice duplicado em guilds, tabela orfa

Revision ID: 46214ac3a288
Revises: c2f5e8a1d4b7
Create Date: 2026-08-03 12:00:00.000000

Achados da auditoria de producao (multi-tenant/banco):
- `guilds` tinha DOIS indices identicos na coluna guild_id
  (guilds_guild_id_key, da unique constraint, e ix_guilds_guild_id, de um
  index=True redundante no model) — puro overhead de escrita sem ganho de
  leitura. Corrigido no model (database/models/guild.py) e aqui no banco.
- `guild_messages` existe no banco de producao mas nao tem NENHUM model,
  repository ou migration correspondente no codigo (nao aparece em nenhum
  commit do historico) — tabela orfa, vazia (0 linhas), provavelmente um
  prototipo abandonado de mensagens customizaveis por guild. Removida.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '46214ac3a288'
down_revision: Union[str, None] = 'c2f5e8a1d4b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_indexes = {ix["name"] for ix in inspector.get_indexes("guilds")}
    if "ix_guilds_guild_id" in existing_indexes:
        op.drop_index("ix_guilds_guild_id", table_name="guilds")

    if "guild_messages" in inspector.get_table_names():
        op.drop_table("guild_messages")


def downgrade() -> None:
    op.create_table(
        "guild_messages",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("message_key", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("footer", sa.String(), nullable=True),
        sa.Column("color", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "message_key"),
    )
    op.create_index("ix_guilds_guild_id", "guilds", ["guild_id"], unique=False)
