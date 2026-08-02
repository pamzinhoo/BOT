from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


# valores validos de pix_key_type — coluna String plain (nao Enum nativo do
# Postgres) de proposito, pra usar o FieldKind.CHOICE generico do painel de
# config sem precisar de conversao Enum<->str (mesmo padrao de
# MonetizationGatewaySettings.provider/environment).
PIX_KEY_TYPES = [
    ("cpf", "CPF"),
    ("cnpj", "CNPJ"),
    ("email", "E-mail"),
    ("telefone", "Telefone"),
    ("aleatoria", "Chave Aleatória"),
]


class PixManualSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — dados da chave PIX usados pelo ManualProvider pra
    gerar o payload EMV/QR de cada cobranca localmente (sem gateway externo).
    A chave PIX NAO e um segredo (o proprio objetivo dela e ser mostrada ao
    pagador), mas so admins com acesso ao /config painel podem ve-la ou
    edita-la — mesma protecao de qualquer outra config sensivel da guild."""

    __tablename__ = "pix_manual_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    pix_key_type: Mapped[str | None] = mapped_column(String(20))
    pix_key: Mapped[str | None] = mapped_column(Text)
    receiver_name: Mapped[str | None] = mapped_column(String(100))
    receiver_city: Mapped[str | None] = mapped_column(String(50))
    bank_name: Mapped[str | None] = mapped_column(String(100))
    buyer_message: Mapped[str | None] = mapped_column(Text)
    expiration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    send_qr_code: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    send_copy_paste: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # sempre True enquanto nao existir confirmacao automatica — persistido
    # (em vez de fixo no codigo) pra ja existir o campo quando um gateway
    # automatico for ligado no futuro.
    manual_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    @property
    def is_configured(self) -> bool:
        return bool(self.pix_key and self.receiver_name)
