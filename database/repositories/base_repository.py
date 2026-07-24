from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.base import Base


class BaseRepository[ModelType: Base]:
    """Operacoes CRUD genericas reutilizadas pelos repositorios concretos.

    Cada repositorio concreto (ex.: TicketRepository) deve herdar desta classe
    informando o model correspondente, e pode adicionar metodos de consulta
    especificos do seu dominio.
    """

    model: type[ModelType]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, id_: Any) -> ModelType | None:
        return await self.session.get(self.model, id_)

    async def list_all(self) -> list[ModelType]:
        result = await self.session.execute(select(self.model))
        return list(result.scalars().all())

    async def add(self, entity: ModelType) -> ModelType:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity: ModelType) -> None:
        await self.session.delete(entity)
        await self.session.flush()
