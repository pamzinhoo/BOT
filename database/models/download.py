from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DownloadStatus(enum.Enum):
    AUTHORIZED = "authorized"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class Download(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Trilha de auditoria de cada autorizacao de download de DLC/base game —
    1 linha por URL assinada emitida pelo backend (ver secao 6 do documento de
    arquitetura). E o registro que prova que uma License estava ACTIVE no
    momento exato da autorizacao, mesmo que a License seja revogada depois.

    FKs de player/device usam SET NULL: a linha de auditoria tem que
    sobreviver mesmo que o dispositivo seja removido. product_id usa RESTRICT
    igual PaymentHistory.plan_id — nunca perder de qual produto era o
    download so porque o produto foi desativado.
    """

    __tablename__ = "downloads"

    player_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("players.id", ondelete="SET NULL"), index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    manifest_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_manifest_entries.id", ondelete="SET NULL")
    )

    status: Mapped[DownloadStatus] = mapped_column(
        Enum(DownloadStatus, name="download_status"),
        nullable=False,
        default=DownloadStatus.AUTHORIZED,
        index=True,
    )
    signed_url_issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signed_url_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    bytes_transferred: Mapped[int | None] = mapped_column(BigInteger)
    client_sha256: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(INET)
    failure_reason: Mapped[str | None] = mapped_column(String(200))
