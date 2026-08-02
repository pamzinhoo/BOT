from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


class PunishmentReviewRole(Base, UUIDPrimaryKeyMixin):
    """1 linha por cargo removido durante o isolamento de uma punicao em analise
    (Etapa 22) — usado pra restaurar os cargos originais ao aceitar/negar o recurso
    ou quando o prazo de analise expira."""

    __tablename__ = "punishment_review_roles"

    punishment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("punishments.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
