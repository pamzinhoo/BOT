from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ManifestEntryType(enum.Enum):
    FULL = "full"
    PATCH = "patch"


class GameManifestEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por versao publicada de um Product (base game, DLC, etc) no
    storage (Cloudflare R2). O Launcher compara versao/sha256 local contra a
    entrada com `is_current=True` pra decidir se precisa atualizar (ver
    docs/LIMERENCE_LAUNCHER_ARCHITECTURE.md secao 7). `entry_type=PATCH` e
    suporte para atualizacao incremental futura — a primeira versao do
    sistema so publica FULL.
    """

    __tablename__ = "game_manifest_entries"
    __table_args__ = (
        UniqueConstraint("product_id", "version", "entry_type", name="uq_manifest_product_version_type"),
        CheckConstraint("char_length(sha256) = 64", name="ck_manifest_sha256_length"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)

    entry_type: Mapped[ManifestEntryType] = mapped_column(
        Enum(ManifestEntryType, name="manifest_entry_type"), nullable=False, default=ManifestEntryType.FULL
    )
    depends_on: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    release_notes: Mapped[str | None] = mapped_column(Text)

    created_by_staff_id: Mapped[int | None] = mapped_column(BigInteger)
