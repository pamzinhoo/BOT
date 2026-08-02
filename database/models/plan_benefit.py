from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


class PlanBenefit(Base, UUIDPrimaryKeyMixin):
    """1 linha por beneficio de um plano — texto livre, sem lista fixa. A loja
    so exibe o que estiver cadastrado aqui, na ordem definida por `position`."""

    __tablename__ = "plan_benefits"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
