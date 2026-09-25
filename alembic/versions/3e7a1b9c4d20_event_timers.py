"""event timers

Revision ID: 3e7a1b9c4d20
Revises: 2d6f9a1c8b44
Create Date: 2026-09-25 17:55:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3e7a1b9c4d20"
down_revision: str | None = "2d6f9a1c8b44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    status = sa.Enum("ACTIVE", "PAUSED", "FINISHED", "CANCELED", "ERROR", name="event_timer_status")
    status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "event_timers",
        sa.Column("creator_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("mention_everyone", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("repeat_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_announcement_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_announcement_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", status, nullable=False, server_default="ACTIVE"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.Column("image_storage_path", sa.String(length=1000), nullable=True),
        sa.Column("image_filename", sa.String(length=255), nullable=True),
        sa.Column("image_content_type", sa.String(length=100), nullable=True),
        sa.Column("image_size", sa.Integer(), nullable=True),
        sa.Column("image_delete_pending", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_event_timers_guild_id"), "event_timers", ["guild_id"], unique=False)
    op.create_index("ix_event_timers_due", "event_timers", ["status", "next_announcement_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_event_timers_due", table_name="event_timers")
    op.drop_index(op.f("ix_event_timers_guild_id"), table_name="event_timers")
    op.drop_table("event_timers")
    sa.Enum(name="event_timer_status").drop(op.get_bind(), checkfirst=True)
