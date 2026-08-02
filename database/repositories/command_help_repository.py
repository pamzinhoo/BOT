from __future__ import annotations

from sqlalchemy import select

from database.models.command_help import CommandHelp
from database.repositories.base_repository import BaseRepository


class CommandHelpRepository(BaseRepository[CommandHelp]):
    model = CommandHelp

    async def get_by_command_name(self, command_name: str) -> CommandHelp | None:
        result = await self.session.execute(
            select(CommandHelp).where(CommandHelp.command_name == command_name)
        )
        return result.scalar_one_or_none()

    async def list_by_category(self, category: str) -> list[CommandHelp]:
        result = await self.session.execute(
            select(CommandHelp)
            .where(CommandHelp.category == category, CommandHelp.enabled.is_(True))
            .order_by(CommandHelp.command_name)
        )
        return list(result.scalars().all())

    async def list_enabled(self) -> list[CommandHelp]:
        result = await self.session.execute(
            select(CommandHelp)
            .where(CommandHelp.enabled.is_(True))
            .order_by(CommandHelp.category, CommandHelp.command_name)
        )
        return list(result.scalars().all())
