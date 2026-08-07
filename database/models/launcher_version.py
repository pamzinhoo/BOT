from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Enum, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LauncherPlatform(enum.Enum):
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"


class LauncherVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Auto-atualizacao do proprio Launcher (Tauri) — mesmo mecanismo de
    manifest/sha256 usado pro jogo, mas versionado por plataforma, ja que o
    binario do Launcher e nativo por SO."""

    __tablename__ = "launcher_versions"
    __table_args__ = (
        UniqueConstraint("version", "platform", name="uq_launcher_versions_version_platform"),
        CheckConstraint("char_length(sha256) = 64", name="ck_launcher_versions_sha256_length"),
    )

    version: Mapped[str] = mapped_column(String(32), nullable=False)
    platform: Mapped[LauncherPlatform] = mapped_column(
        Enum(LauncherPlatform, name="launcher_platform"), nullable=False, index=True
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    release_notes: Mapped[str | None] = mapped_column(Text)

    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by_staff_id: Mapped[int | None] = mapped_column(BigInteger)
