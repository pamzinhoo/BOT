"""Proteção contra exclusão em massa de canais e revisão persistente."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a6d2e8c4f901"
down_revision = "3e7a1b9c4d20"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("channel_guard_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("channel_guard_threshold", sa.Integer(), nullable=False, server_default="3"),
        sa.Column(
            "channel_guard_window_seconds", sa.Integer(), nullable=False, server_default="30"
        ),
        sa.Column("channel_guard_log_channel_id", sa.BigInteger()),
        sa.Column("channel_guard_review_channel_id", sa.BigInteger()),
        sa.Column(
            "channel_guard_reviewer_role_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("channel_guard_banned_role_id", sa.BigInteger()),
    ):
        op.add_column("guild_settings", column)
    op.create_table(
        "channel_guard_incidents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("guild_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role_ids", postgresql.JSONB(), nullable=False),
        sa.Column("channels", postgresql.JSONB(), nullable=False),
        sa.Column("restored_ids", postgresql.JSONB(), nullable=False),
        sa.Column("errors", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reviewer_id", sa.BigInteger()),
        sa.Column("review_channel_id", sa.BigInteger()),
        sa.Column("review_message_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("channel_guard_incidents")
    for name in (
        "enabled",
        "threshold",
        "window_seconds",
        "log_channel_id",
        "review_channel_id",
        "reviewer_role_ids",
        "banned_role_id",
    ):
        op.drop_column("guild_settings", f"channel_guard_{name}")
