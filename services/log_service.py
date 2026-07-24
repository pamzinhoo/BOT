from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import discord

from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.log import LogAction, LogEntry
from database.repositories.guild_settings_repository import GuildSettingsRepository
from database.repositories.log_repository import LogRepository
from utils.constants import EMBED_COLOR_DEFAULT, LOG_ACTION_LABELS

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_TICKET_ACTION_LABELS: dict[LogAction, str] = {
    LogAction.CLAIM: "Ticket assumido",
    LogAction.UNCLAIM: "Ticket liberado",
    LogAction.FECHAMENTO: "Ticket fechado",
    LogAction.REABERTURA: "Ticket reaberto",
}


class LogService:
    def __init__(self, database: Database, bot: "LimerenceBot") -> None:
        self._database = database
        self._bot = bot

    async def record(
        self,
        *,
        guild_id: int,
        action: LogAction,
        message: str,
        actor_discord_id: int | None = None,
        staff_id: uuid.UUID | None = None,
        ticket_id: uuid.UUID | None = None,
        category_snapshot: str | None = None,
    ) -> LogEntry:
        async with self._database.session() as session:
            entry = await LogRepository(session).add(
                LogEntry(
                    guild_id=guild_id,
                    action=action,
                    actor_discord_id=actor_discord_id,
                    staff_id=staff_id,
                    ticket_id=ticket_id,
                    category_snapshot=category_snapshot,
                    message=message,
                )
            )
            settings = await GuildSettingsRepository(session).get_by_guild_id(guild_id)

        if settings is not None and settings.log_channel_id is not None:
            channel = self._bot.get_channel(settings.log_channel_id)
            if isinstance(channel, discord.abc.Messageable):
                embed = discord.Embed(
                    title=LOG_ACTION_LABELS[action],
                    description=message,
                    color=EMBED_COLOR_DEFAULT,
                )
                await channel.send(embed=embed)

        ticket_label = _TICKET_ACTION_LABELS.get(action)
        if ticket_label is not None:
            await self._bot.audit_log_service.record(
                guild_id=guild_id,
                category=AuditLogCategory.TICKETS,
                action=ticket_label,
                executor_id=actor_discord_id,
                reason=message,
                details={"categoria": category_snapshot} if category_snapshot else None,
            )

        return entry
