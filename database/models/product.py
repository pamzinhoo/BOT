from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProductType(enum.Enum):
    PERMANENT = "permanent"
    SUBSCRIPTION = "subscription"
    DLC = "dlc"
    COSMETIC = "cosmetic"
    DIGITAL_CONTENT = "digital_content"


class Product(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Catalogo generico de tudo que pode ser vendido/concedido no ecossistema
    do jogo (base game, DLC, pacotes de assinatura, cosmetico, etc). Posse de
    um Product por um Player e sempre representada por License — nunca existe
    um model separado por tipo de produto.

    Exclusao e SOFT (`is_active=False` + `deleted_at`), igual ao padrao ja
    usado em DiscountCoupon: License referencia Product com FK RESTRICT,
    entao remover a linha de verdade quebraria o historico de compra.
    """

    __tablename__ = "products"

    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    product_type: Mapped[ProductType] = mapped_column(Enum(ProductType, name="product_type"), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    price_amount: Mapped[int | None] = mapped_column(Integer)  # centavos
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="BRL")

    # Cargo que libera acesso SEM compra — so usado quando product_type=DLC e
    # price_amount e None/0 (DLC gratuita). O cargo, nao a License, e a fonte
    # de verdade de posse nesse caso; a License gerada (purchase_source=
    # "role_grant") e so a representacao persistida desse estado, mantida em
    # sincronia por listener de member_update + reconciliacao periodica (ver
    # services/dlc_service.py). DLC paga NUNCA usa estes campos — o cargo
    # dela vive em Plan.role_id, junto do restante do pipeline de pagamento.
    # guild_id fica junto do role_id porque Product e global mas o cargo
    # pertence a uma guild especifica (normalmente a oficial do jogo).
    required_role_id: Mapped[int | None] = mapped_column(BigInteger)
    required_role_guild_id: Mapped[int | None] = mapped_column(BigInteger)

    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by_staff_id: Mapped[int | None] = mapped_column(BigInteger)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
