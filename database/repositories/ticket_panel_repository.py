from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.ticket_form_response import TicketFormResponse
from database.models.ticket_panel import TicketPanel
from database.models.ticket_panel_form_field import TicketPanelFormField
from database.models.ticket_panel_group import TicketPanelGroup
from database.repositories.base_repository import BaseRepository


class TicketPanelRepository(BaseRepository[TicketPanel]):
    model = TicketPanel

    async def get_by_id(self, id_: uuid.UUID) -> TicketPanel | None:
        return await self.session.get(TicketPanel, id_)

    async def get_by_key(self, guild_id: int, key: str) -> TicketPanel | None:
        result = await self.session.execute(
            select(TicketPanel).where(TicketPanel.guild_id == guild_id, TicketPanel.key == key)
        )
        return result.scalar_one_or_none()

    async def list_by_guild(
        self, guild_id: int, *, only_enabled: bool = False
    ) -> list[TicketPanel]:
        stmt = select(TicketPanel).where(TicketPanel.guild_id == guild_id)
        if only_enabled:
            stmt = stmt.where(TicketPanel.enabled.is_(True))
        stmt = stmt.order_by(TicketPanel.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_published(self) -> list[TicketPanel]:
        """Todos os paineis ja publicados (de todas as guilds) — usado so no
        boot pra re-registrar as views persistentes dos botoes."""
        result = await self.session.execute(
            select(TicketPanel).where(
                TicketPanel.channel_id.is_not(None), TicketPanel.message_id.is_not(None)
            )
        )
        return list(result.scalars().all())


class TicketPanelGroupRepository(BaseRepository[TicketPanelGroup]):
    model = TicketPanelGroup

    async def get_by_id(self, id_: uuid.UUID) -> TicketPanelGroup | None:
        return await self.session.get(TicketPanelGroup, id_)

    async def list_by_guild(self, guild_id: int) -> list[TicketPanelGroup]:
        result = await self.session.execute(
            select(TicketPanelGroup)
            .where(TicketPanelGroup.guild_id == guild_id)
            .order_by(TicketPanelGroup.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_published(self) -> list[TicketPanelGroup]:
        """Todos os combos ja publicados (de todas as guilds) — usado so no
        boot pra re-registrar as views persistentes dos botoes."""
        result = await self.session.execute(
            select(TicketPanelGroup).where(
                TicketPanelGroup.channel_id.is_not(None),
                TicketPanelGroup.message_id.is_not(None),
            )
        )
        return list(result.scalars().all())


class TicketPanelFormFieldRepository(BaseRepository[TicketPanelFormField]):
    model = TicketPanelFormField

    async def get_by_id(self, id_: uuid.UUID) -> TicketPanelFormField | None:
        return await self.session.get(TicketPanelFormField, id_)

    async def list_by_panel(self, panel_id: uuid.UUID) -> list[TicketPanelFormField]:
        result = await self.session.execute(
            select(TicketPanelFormField)
            .where(TicketPanelFormField.panel_id == panel_id)
            .order_by(TicketPanelFormField.position.asc())
        )
        return list(result.scalars().all())


class TicketFormResponseRepository(BaseRepository[TicketFormResponse]):
    model = TicketFormResponse

    async def list_by_ticket(self, ticket_id: uuid.UUID) -> list[TicketFormResponse]:
        result = await self.session.execute(
            select(TicketFormResponse)
            .where(TicketFormResponse.ticket_id == ticket_id)
            .order_by(TicketFormResponse.position.asc())
        )
        return list(result.scalars().all())
