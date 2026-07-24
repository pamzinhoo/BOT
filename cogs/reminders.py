from __future__ import annotations

from datetime import UTC, datetime

import discord
from discord.ext import commands, tasks

from core.bot import LimerenceBot
from core.logger import get_logger
from database.models.guild_settings import GuildSettings
from database.models.log import LogAction

logger = get_logger("reminders")

_CHECK_INTERVAL_MINUTES = 5

# (minutos decorridos, tier) — escalada crescente. So dispara enquanto o
# ticket nao tiver recebido a primeira resposta da staff (assumido ou nao).
_TIERS: list[tuple[int, int]] = [(20, 1), (60, 2), (120, 3)]


class RemindersCog(commands.Cog):
    """Lembra a staff de tickets parados (sem primeira resposta), escalando
    a urgencia: 20min avisa no canal, 1h marca o Moderador, 2h marca o CEO."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self.check_stale_tickets.start()

    def cog_unload(self) -> None:
        self.check_stale_tickets.cancel()

    @tasks.loop(minutes=_CHECK_INTERVAL_MINUTES)
    async def check_stale_tickets(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self._check_guild(guild)
            except Exception:
                logger.exception("Falha ao checar lembretes na guild %s.", guild.id)

    @check_stale_tickets.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _check_guild(self, guild: discord.Guild) -> None:
        settings = await self.bot.config_service.get_settings(guild.id)
        now = datetime.now(UTC)

        for ticket in await self.bot.ticket_service.list_awaiting_first_response(guild.id):
            channel = guild.get_channel(ticket.channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue

            elapsed_minutes = (now - ticket.created_at).total_seconds() / 60
            target_tier = 0
            for threshold_minutes, tier in _TIERS:
                if elapsed_minutes >= threshold_minutes:
                    target_tier = tier

            if target_tier <= ticket.reminder_tier_sent:
                continue

            await self._send_reminder(guild, channel, settings, target_tier)
            await self.bot.ticket_service.mark_reminder_tier(channel.id, target_tier)

    async def _send_reminder(
        self, guild: discord.Guild, channel: discord.TextChannel, settings: GuildSettings, tier: int
    ) -> None:
        if tier == 1:
            content = None
            description = "Esse ticket ainda não recebeu a primeira resposta da staff. Alguém dá uma olhada?"
        elif tier == 2:
            content = f"<@&{settings.moderator_role_id}>" if settings.moderator_role_id else None
            description = "Já se passou 1 hora sem resposta! Moderação, precisa de atenção aqui."
        else:
            content = f"<@&{settings.ceo_role_id}>" if settings.ceo_role_id else None
            description = "2 horas sem resposta. CEO, esse ticket está sendo esquecido."

        await channel.send(
            content=content,
            embed=discord.Embed(title="⏰ Lembrete de ticket parado", description=description),
        )

        await self.bot.log_service.record(
            guild_id=guild.id,
            action=LogAction.ATUALIZACAO_AUTOMATICA,
            message=f"Lembrete tier {tier} enviado no canal <#{channel.id}> — sem primeira resposta.",
        )


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(RemindersCog(bot))
