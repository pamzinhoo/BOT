"""scheduled job state

Revision ID: 2d6f9a1c8b44
Revises: f8b3d6a2c9e5
Create Date: 2026-09-07 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "2d6f9a1c8b44"
down_revision: str | None = "f8b3d6a2c9e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_job_state",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("job_name", sa.String(length=80), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "job_name", name="uq_scheduled_job_state_guild_job"),
    )
    op.create_index(op.f("ix_scheduled_job_state_guild_id"), "scheduled_job_state", ["guild_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_scheduled_job_state_guild_id"), table_name="scheduled_job_state")
    op.drop_table("scheduled_job_state")
