"""indices em guild_id/plan_id nas tabelas mais consultadas (auditoria)

Revision ID: 9f1c7d2a5b4e
Revises: 46214ac3a288
Create Date: 2026-08-03 13:00:00.000000

Achados da auditoria (repositories/performance): varias das tabelas com
maior volume de linhas (compartilhadas entre TODAS as guilds, crescimento
sem limite) filtram por guild_id em praticamente toda query do repository
correspondente mas nao tinham indice nessa coluna — cada consulta virava um
sequential scan que so piora conforme o numero de clientes cresce:
- audit_log_entries, punishments, payment_history, verification_sessions,
  boosters, partnerships, staff, subscriptions, plans, automod_config,
  automod_logs (guild_id)
- plan_benefits (plan_id, FK sem indice, consultado toda vez que a loja
  renderiza os beneficios de um plano)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f1c7d2a5b4e'
down_revision: Union[str, None] = '46214ac3a288'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GUILD_ID_TABLES = [
    "audit_log_entries",
    "punishments",
    "payment_history",
    "verification_sessions",
    "boosters",
    "partnerships",
    "staff",
    "subscriptions",
    "plans",
    "automod_config",
    "automod_logs",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in _GUILD_ID_TABLES:
        if table not in inspector.get_table_names():
            continue
        index_name = f"ix_{table}_guild_id"
        existing = {ix["name"] for ix in inspector.get_indexes(table)}
        if index_name not in existing:
            op.create_index(index_name, table, ["guild_id"], unique=False)

    if "plan_benefits" in inspector.get_table_names():
        existing = {ix["name"] for ix in inspector.get_indexes("plan_benefits")}
        if "ix_plan_benefits_plan_id" not in existing:
            op.create_index("ix_plan_benefits_plan_id", "plan_benefits", ["plan_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "plan_benefits" in inspector.get_table_names():
        existing = {ix["name"] for ix in inspector.get_indexes("plan_benefits")}
        if "ix_plan_benefits_plan_id" in existing:
            op.drop_index("ix_plan_benefits_plan_id", table_name="plan_benefits")

    for table in _GUILD_ID_TABLES:
        if table not in inspector.get_table_names():
            continue
        index_name = f"ix_{table}_guild_id"
        existing = {ix["name"] for ix in inspector.get_indexes(table)}
        if index_name in existing:
            op.drop_index(index_name, table_name=table)
