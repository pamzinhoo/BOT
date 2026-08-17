from __future__ import annotations

import discord
from discord.ext import commands, tasks

from core.bot import LimerenceBot
from core.logger import get_logger

logger = get_logger("dlc")


class DlcCog(commands.Cog):
    """Deteccao automatica de cargo de DLC gratuita via on_member_update —
    toda a logica de negocio vive em DlcService, esta Cog so ouve o evento e
    delega (mesmo padrao de cogs/partnership.py). O cargo e a fonte de
    verdade de posse: ganhar concede License(source=role_grant), perder
    revoga. Reconciliacao periodica cobre bot offline/edicao manual de cargo
    (mesma rede de seguranca que ReconciliationService/PartnershipService
    ja usam pro resto do sistema — nunca decide posse so por evento)."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self.reconcile_dlcs.start()

    def cog_unload(self) -> None:
        self.reconcile_dlcs.cancel()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.roles == after.roles:
            return

        try:
            products = await self.bot.dlc_service.list_free_dlcs_by_guild(after.guild.id)
        except Exception:
            logger.exception("Falha ao ler DLCs gratuitas na guild %s.", after.guild.id)
            return
        if not products:
            return

        before_role_ids = {role.id for role in before.roles}
        after_role_ids = {role.id for role in after.roles}

        for product in products:
            role_id = product.required_role_id
            if role_id is None:
                continue
            had_role = role_id in before_role_ids
            has_role = role_id in after_role_ids
            if had_role == has_role:
                continue
            try:
                if has_role:
                    await self.bot.dlc_service.sync_role_gained(after.id, product)
                else:
                    await self.bot.dlc_service.sync_role_lost(after.id, product)
            except Exception:
                logger.exception(
                    "Falha ao sincronizar DLC %s (guild %s) para discord_id %s.",
                    product.id, after.guild.id, after.id,
                )

    @tasks.loop(hours=1)
    async def reconcile_dlcs(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self.bot.dlc_service.reconcile_guild(guild)
            except Exception:
                logger.exception("Falha ao reconciliar DLCs gratuitas na guild %s.", guild.id)

    @reconcile_dlcs.before_loop
    async def before_reconcile_dlcs(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(DlcCog(bot))
