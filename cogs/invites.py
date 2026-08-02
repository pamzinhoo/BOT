from __future__ import annotations

import discord
from discord.ext import commands

from core.bot import LimerenceBot
from core.logger import get_logger
from utils.checks import member_can_create_invite
from utils.constants import EMBED_COLOR_WARNING

logger = get_logger("invites")


class InvitesCog(commands.Cog):
    """Restringe criacao de convites do servidor ao(s) cargo(s) configurados em
    /config painel > Permissoes > Quem pode criar convites. Sem cargo configurado,
    nao ha restricao (comportamento padrao do Discord)."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        guild = invite.guild
        if not isinstance(guild, discord.Guild) or invite.inviter is None:
            return

        member = guild.get_member(invite.inviter.id)
        if member is None:
            try:
                member = await guild.fetch_member(invite.inviter.id)
            except discord.HTTPException:
                return

        permission_settings = await self.bot.config_service.get_permission_settings(guild.id)
        if member_can_create_invite(member, permission_settings):
            return

        try:
            await invite.delete(reason="Cargo do autor nao esta liberado para criar convites.")
        except discord.HTTPException:
            logger.warning("Falha ao apagar convite nao autorizado na guild %s.", guild.id)
            return

        settings = await self.bot.config_service.get_settings(guild.id)
        if settings.log_channel_id is None:
            return
        log_channel = guild.get_channel(settings.log_channel_id)
        if not isinstance(log_channel, discord.TextChannel):
            return

        embed = discord.Embed(
            title="🔗 Convite bloqueado",
            description=(
                f"{member.mention} tentou criar um convite em {invite.channel.mention if isinstance(invite.channel, discord.abc.GuildChannel) else invite.channel} "
                "mas nao tem o cargo autorizado. Convite apagado automaticamente."
            ),
            color=EMBED_COLOR_WARNING,
        )
        await log_channel.send(embed=embed)


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(InvitesCog(bot))
