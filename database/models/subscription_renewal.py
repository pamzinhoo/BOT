from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SubscriptionMessageType(enum.Enum):
    """Um tipo por evento do ciclo de renovacao. Mesmo padrao de PlanMessageType:
    sem linha cadastrada, o servico usa o texto padrao (editavel a qualquer
    momento pelo admin) — nunca existe texto fixo inalcancavel."""

    REMINDER = "reminder"
    LAST_REMINDER = "last_reminder"
    EXPIRED = "expired"
    RENEWED = "renewed"
    GRACE_PERIOD = "grace_period"


class SubscriptionRenewalButtonKey(enum.Enum):
    """Botoes anexados as mensagens de renovacao. RENEW reaproveita o fluxo de
    compra da Loja (PaymentService/PaymentProvider) — nunca fala com gateway."""

    RENEW = "renew"
    VIEW_PLAN = "view_plan"
    OPEN_STORE = "open_store"
    CLOSE = "close"


class SubscriptionRenewalSettings(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por guild — comportamento do sistema de renovacao de assinaturas
    (/config painel > Monetizacao > Renovacao de Assinaturas). Nada aqui e fixo
    ou global: cada servidor define avisos, carencia, canais e remocoes."""

    __tablename__ = "subscription_renewal_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notify_via_dm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_via_channel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    renewal_channel_id: Mapped[int | None] = mapped_column(BigInteger)

    grace_period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # validado na camada de UI (1/6/12/24) — a coluna aceita qualquer inteiro
    # pra nao travar migracao caso a lista de opcoes mude.
    check_interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)

    remove_roles_on_expire: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    remove_benefits_on_expire: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    end_subscription_on_expire: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    log_audit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    send_dm_on_removal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    continue_reminders_during_grace: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )


class SubscriptionReminderDay(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por aviso configurado (ex.: 7 dias antes, 3 dias antes, 1 dia
    antes). Lista ilimitada, ordenavel e desativavel individualmente."""

    __tablename__ = "subscription_reminder_days"
    __table_args__ = (
        UniqueConstraint("guild_id", "days_before", name="uq_subscription_reminder_day"),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    days_before: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SubscriptionMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por (guild, tipo de mensagem de renovacao) — espelha
    PlanMessage: sem linha cadastrada o servico cai no texto padrao."""

    __tablename__ = "subscription_messages"
    __table_args__ = (
        UniqueConstraint("guild_id", "message_type", name="uq_subscription_message_type"),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    message_type: Mapped[SubscriptionMessageType] = mapped_column(
        Enum(SubscriptionMessageType, name="subscription_message_type"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)


class SubscriptionRenewalButton(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por (guild, botao) — label/emoji/ordem/ativo editaveis. As 4
    chaves padrao sao semeadas no primeiro acesso (get_or_create_defaults)."""

    __tablename__ = "subscription_renewal_buttons"
    __table_args__ = (
        UniqueConstraint("guild_id", "key", name="uq_subscription_renewal_button_key"),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    key: Mapped[SubscriptionRenewalButtonKey] = mapped_column(
        Enum(SubscriptionRenewalButtonKey, name="subscription_renewal_button_key"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    label: Mapped[str | None] = mapped_column(String(80))
    emoji: Mapped[str | None] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SubscriptionReminder(Base, UUIDPrimaryKeyMixin):
    """Livro-razao anti-duplicacao: 1 linha por aviso/evento ja enviado pra uma
    assinatura num periodo. O scheduler consulta esta tabela antes de qualquer
    envio, entao o mesmo lembrete nunca sai duas vezes — nem depois de restart.

    `period_end` guarda o current_period_end vigente no momento do envio: e o
    que permite o mesmo `reminder_type` voltar a ser enviado no ciclo seguinte
    depois de uma renovacao, sem nunca repetir dentro do mesmo ciclo."""

    __tablename__ = "subscription_reminders"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "reminder_type", "period_end", name="uq_subscription_reminder_once"
        ),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reminder_type: Mapped[str] = mapped_column(String(50), nullable=False)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(20), nullable=False, default="sent")
