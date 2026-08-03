from __future__ import annotations

import discord
from discord.ext import commands, tasks

from core.bot import LimerenceBot
from core.logger import get_logger
from services.partnership_service import member_has_partnership_role

logger = get_logger("partnership")


class PartnershipCog(commands.Cog):
    """Deteccao automatica de cargo Parceiro/Streamer via on_member_update —
    toda a logica de negocio vive em PartnershipService, esta Cog so ouve o
    evento e delega. Duas varreduras periodicas complementam: uma reconcilia
    cargo x canal (cobre gaps de gateway), outra dispara a divulgacao
    automatica em rodizio entre os parceiros ativos."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self.reconcile_partnerships.start()
        self.announcement_tick.start()

    def cog_unload(self) -> None:
        self.reconcile_partnerships.cancel()
        self.announcement_tick.cancel()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.roles == after.roles:
            return

        try:
            partner_role_id, streamer_role_id = await self.bot.partnership_service.get_partner_role_ids(
                after.guild.id
            )
        except Exception:
            logger.exception("Falha ao ler cargos de parceria na guild %s.", after.guild.id)
            return

        had_role = member_has_partnership_role(before, partner_role_id, streamer_role_id)
        has_role = member_has_partnership_role(after, partner_role_id, streamer_role_id)
        if had_role == has_role:
            return

        try:
            if has_role:
                await self.bot.partnership_service.handle_role_gained(after)
            else:
                await self.bot.partnership_service.handle_role_lost(after)
        except Exception:
            logger.exception("Falha ao processar mudança de cargo de parceria na guild %s.", after.guild.id)

    @tasks.loop(hours=1)
    async def reconcile_partnerships(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self.bot.partnership_service.reconcile_guild(guild)
            except Exception:
                logger.exception("Falha ao reconciliar parcerias na guild %s.", guild.id)

    @reconcile_partnerships.before_loop
    async def before_reconcile_partnerships(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def announcement_tick(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self.bot.partnership_service.run_announcement_tick(guild)
            except Exception:
                logger.exception("Falha ao rodar divulgação automática de parceria na guild %s.", guild.id)

    @announcement_tick.before_loop
    async def before_announcement_tick(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(PartnershipCog(bot))
