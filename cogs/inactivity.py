from __future__ import annotations

from datetime import UTC, datetime

import discord
from discord.ext import commands, tasks

from core.bot import LimerenceBot
from core.logger import get_logger
from database.models.log import LogAction
from database.models.ticket import Ticket
from services.ticket_service import TicketNotClaimedError, TicketNotFoundError
from utils.achievements import announce_achievements
from utils.constants import EMBED_COLOR_DANGER
from utils.ticket_lifecycle import schedule_channel_deletion
from views.evaluation_view import EvaluationView
from views.ticket_closed_view import TicketClosedView

logger = get_logger("inactivity")

_CHECK_INTERVAL_MINUTES = 5
_OWNER_SILENCE_HOURS = 24


class InactivityCog(commands.Cog):
    """Duas regras de auto-fechamento, checadas periodicamente:

    1. Canal inteiro sem atividade por `inactive_after_minutes` (config por
       guild, opcional) — so em tickets ja assumidos.
    2. Dono do ticket sem mandar mensagem por 24h (fixo, sempre ativo) —
       fecha se assumido, cancela se ninguem assumiu ainda.
    """

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self.check_inactive_tickets.start()

    def cog_unload(self) -> None:
        self.check_inactive_tickets.cancel()

    @tasks.loop(minutes=_CHECK_INTERVAL_MINUTES)
    async def check_inactive_tickets(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self._check_guild(guild)
            except Exception:
                logger.exception("Falha ao checar inatividade na guild %s.", guild.id)

    @check_inactive_tickets.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _check_guild(self, guild: discord.Guild) -> None:
        settings = await self.bot.config_service.get_settings(guild.id)
        ticket_settings = await self.bot.config_service.get_ticket_settings(guild.id)
        if not ticket_settings.auto_close_enabled:
            return
        now = datetime.now(UTC)

        for ticket in await self.bot.ticket_service.list_open_by_guild(guild.id):
            channel = guild.get_channel(ticket.channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue

            # painel que criou o ticket pode desligar o auto-close so pra ele
            behaviour = await self.bot.ticket_panel_service.behaviour_for_ticket(
                ticket, guild.id
            )
            if not behaviour.auto_close_enabled:
                continue

            if settings.inactive_after_minutes and ticket.claimed_by_staff_id is not None:
                last_activity_at = await self._last_message_at(channel, ticket.created_at)
                elapsed_minutes = (now - last_activity_at).total_seconds() / 60
                if elapsed_minutes >= settings.inactive_after_minutes:
                    await self._auto_close(
                        guild, channel,
                        "Nenhuma mensagem recebida dentro do tempo limite configurado.",
                    )
                    continue

            last_owner_message_at = await self._last_message_at(
                channel, ticket.created_at, author_id=ticket.opened_by_discord_id
            )
            elapsed_hours = (now - last_owner_message_at).total_seconds() / 3600
            if elapsed_hours < _OWNER_SILENCE_HOURS:
                continue

            if ticket.claimed_by_staff_id is not None:
                await self._auto_close(
                    guild, channel,
                    "O autor do ticket ficou 24 horas sem enviar mensagem.",
                )
            else:
                await self._auto_cancel_unclaimed(guild, channel, ticket)

    @staticmethod
    async def _last_message_at(
        channel: discord.TextChannel, fallback: datetime, author_id: int | None = None
    ) -> datetime:
        async for message in channel.history(limit=None):
            if author_id is None or message.author.id == author_id:
                return message.created_at
        return fallback

    async def _auto_close(self, guild: discord.Guild, channel: discord.TextChannel, reason: str) -> None:
        assert self.bot.user is not None
        try:
            result = await self.bot.ticket_service.close_ticket(channel.id, self.bot.user.id)
        except (TicketNotFoundError, TicketNotClaimedError):
            return
        closed_ticket = result.ticket

        await self.bot.log_service.record(
            guild_id=guild.id,
            action=LogAction.FECHAMENTO,
            actor_discord_id=self.bot.user.id,
            staff_id=closed_ticket.claimed_by_staff_id,
            ticket_id=closed_ticket.id,
            category_snapshot=closed_ticket.category.value,
            message=f"Ticket fechado automaticamente — {reason}",
        )
        await self.bot.painel_service.refresh_dashboard(guild.id)

        await channel.send(
            embed=discord.Embed(
                title="✅ Ticket fechado por inatividade",
                description=reason,
                color=EMBED_COLOR_DANGER,
            ),
            view=TicketClosedView(),
        )
        if closed_ticket.claimed_by_staff_id is not None:
            await announce_achievements(
                self.bot, channel, closed_ticket.claimed_by_staff_id, result.unlocked_achievements
            )
        opener = guild.get_member(closed_ticket.opened_by_discord_id)
        eval_settings = await self.bot.config_service.get_evaluation_settings(guild.id)
        behaviour = await self.bot.ticket_panel_service.behaviour_for_ticket(
            closed_ticket, guild.id
        )
        if opener is not None and eval_settings.enabled and behaviour.evaluation_enabled:
            await channel.send(
                content=opener.mention,
                embed=discord.Embed(
                    title="Como foi o seu atendimento?",
                    description="Avalie o suporte que você recebeu.",
                ),
                view=EvaluationView(),
            )

    async def _auto_cancel_unclaimed(
        self, guild: discord.Guild, channel: discord.TextChannel, ticket: Ticket
    ) -> None:
        try:
            cancelled_ticket = await self.bot.ticket_service.cancel_ticket(channel.id)
        except TicketNotFoundError:
            return

        await self.bot.log_service.record(
            guild_id=guild.id,
            action=LogAction.FECHAMENTO,
            actor_discord_id=self.bot.user.id if self.bot.user else None,
            ticket_id=cancelled_ticket.id,
            category_snapshot=cancelled_ticket.category.value,
            message="Ticket cancelado automaticamente — autor ficou 24 horas sem enviar mensagem.",
        )
        await self.bot.painel_service.refresh_dashboard(guild.id)

        await channel.send(
            embed=discord.Embed(
                title="🗑️ Ticket cancelado por inatividade",
                description="O autor do ticket não enviou mensagem em 24 horas e ninguém assumiu o atendimento.",
                color=EMBED_COLOR_DANGER,
            )
        )
        behaviour = await self.bot.ticket_panel_service.behaviour_for_ticket(
            cancelled_ticket, guild.id
        )
        schedule_channel_deletion(
            channel, "cancelado por inatividade do autor", behaviour.delete_delay_seconds
        )


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(InactivityCog(bot))
