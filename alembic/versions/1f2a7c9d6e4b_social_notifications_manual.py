"""notificacoes sociais manuais

Revision ID: 1f2a7c9d6e4b
Revises: f5c8d3a7e1b2
Create Date: 2026-10-08 17:45:00.000000

"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "1f2a7c9d6e4b"
down_revision: str = "f5c8d3a7e1b2"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "social_notifications" in tables:
        return

    op.create_table(
        "social_notifications",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("creator_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "platform",
            sa.Enum(
                "YOUTUBE",
                "TIKTOK",
                "INSTAGRAM",
                "TWITCH",
                "KICK",
                "OTHER",
                name="social_platform",
            ),
            nullable=False,
        ),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("message_template", sa.Text(), nullable=False),
        sa.Column("mention_everyone", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "status",
            sa.Enum("SENT", "FAILED", name="social_notification_status"),
            nullable=False,
            server_default="SENT",
        ),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_social_notifications_guild_id",
        "social_notifications",
        ["guild_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_social_notifications_guild_id", table_name="social_notifications")
    op.drop_table("social_notifications")
    op.execute("DROP TYPE IF EXISTS social_notification_status")
    op.execute("DROP TYPE IF EXISTS social_platform")
