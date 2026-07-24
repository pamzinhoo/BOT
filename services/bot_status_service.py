from __future__ import annotations

from datetime import UTC, datetime

import discord

from database.database import Database
from database.repositories.bot_status_settings_repository import BotStatusSettingsRepository
from database.repositories.guild_settings_repository import GuildSettingsRepository
from database.repositories.ticket_repository import TicketRepository
from utils.checks import member_has_staff_role
from utils.constants import EMBED_COLOR_DANGER, EMBED_COLOR_SUCCESS


def _format_uptime(started_at: datetime) -> str:
    delta = datetime.now(UTC) - started_at
    total_minutes = int(delta.total_seconds() // 60)
    days, rem_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rem_minutes, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


class BotStatusService:
    """Atualiza o painel de status do bot (uma unica mensagem, sempre editada)
    no canal configurado em /config painel, no intervalo escolhido pela guild."""

    def __init__(self, database: Database, bot: discord.Client) -> None:
        self._database = database
        self._bot = bot

    async def refresh(self, guild_id: int) -> None:
        async with self._database.session() as session:
            settings = await GuildSettingsRepository(session).get_by_guild_id(guild_id)
            open_tickets = len(await TicketRepository(session).list_open_by_guild(guild_id))

        channel_id, message_id = await self._channel_and_message(guild_id)
        if channel_id is None:
            return
        channel = self._bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        embed = await self._build_embed(channel.guild, settings, open_tickets)

        message = None
        if message_id is not None:
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                message = None

        if message is not None:
            await message.edit(embed=embed)
            return

        new_message = await channel.send(embed=embed)
        await self._save_message_id(guild_id, new_message.id)

    async def _channel_and_message(self, guild_id: int) -> tuple[int | None, int | None]:
        async with self._database.session() as session:
            settings = await BotStatusSettingsRepository(session).get_or_create(guild_id)
            return settings.channel_id, settings.message_id

    async def _save_message_id(self, guild_id: int, message_id: int) -> None:
        async with self._database.session() as session:
            settings = await BotStatusSettingsRepository(session).get_or_create(guild_id)
            settings.message_id = message_id

    async def _build_embed(
        self, guild: discord.Guild, settings: object, open_tickets: int
    ) -> discord.Embed:
        db_ok = True
        try:
            await self._database.check_connection()
        except Exception:
            db_ok = False

        gateway_ok = not self._bot.is_closed() and self._bot.latency < 1.0
        staff_online = self._count_staff_online(guild, settings)
        started_at = getattr(self._bot, "started_at", datetime.now(UTC))

        color = EMBED_COLOR_SUCCESS if (db_ok and gateway_ok) else EMBED_COLOR_DANGER
        embed = discord.Embed(title="🤖 BOT LIMERENCE STATUS", color=color)
        embed.add_field(name="Status", value="🟢 Online", inline=False)
        embed.add_field(name="⏱ Uptime", value=_format_uptime(started_at), inline=False)
        embed.add_field(
            name="🔄 Último restart", value=started_at.strftime("%d/%m/%Y %H:%M"), inline=False
        )
        embed.add_field(
            name="💾 Banco",
            value="🟢 PostgreSQL conectado" if db_ok else "🔴 PostgreSQL indisponível",
            inline=False,
        )
        embed.add_field(
            name="🌐 Discord",
            value="🟢 Gateway normal" if gateway_ok else "🔴 Gateway instável",
            inline=False,
        )
        embed.add_field(name="📂 Tickets abertos", value=str(open_tickets), inline=False)
        embed.add_field(name="👮 Staff online", value=str(staff_online), inline=False)
        return embed

    def _count_staff_online(self, guild: discord.Guild, settings: object) -> int:
        if settings is None:
            return 0
        count = 0
        for member in guild.members:
            if member.bot:
                continue
            if member.status == discord.Status.offline:
                continue
            if member_has_staff_role(member, settings):  # type: ignore[arg-type]
                count += 1
        return count
