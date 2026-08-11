from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import LimerenceBot
from utils.checks import is_admin, member_is_admin
from views.monetization_panel_view import MonetizationMenuView, monetization_menu_embed
from views.shop_view import ShopView


class ShopCog(commands.Cog):
    """Loja de Planos (Monetização) — white-label: nada aqui e fixo, tudo vem
    dos planos cadastrados pela guild em /monetizacao."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    @app_commands.command(name="loja", description="Mostra os planos de apoio disponíveis neste servidor.")
    @app_commands.describe(
        publicar="Publica (ou atualiza) o painel fixo da loja neste canal — só staff/admin."
    )
    async def loja(self, interaction: discord.Interaction, publicar: bool = False) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)

        if publicar:
            if not await member_is_admin(interaction) or not isinstance(interaction.channel, discord.TextChannel):
                await interaction.followup.send(
                    "Apenas admins podem publicar o painel da loja, e só em canal de texto.",
                    ephemeral=True,
                )
                return
            await self.bot.painel_service.publish_shop_panel(interaction.guild_id, interaction.channel.id)
            await interaction.followup.send(
                f"✅ Painel da loja publicado em {interaction.channel.mention}. "
                "Ele se atualiza sozinho quando os planos mudarem.",
                ephemeral=True,
            )
            return

        plans = await self.bot.plan_service.list_plans(interaction.guild_id, only_active=True)
        if not plans:
            await interaction.followup.send(
                "Nenhum plano disponível no momento.", ephemeral=True
            )
            return

        benefits_by_plan = {}
        for plan in plans:
            benefits = await self.bot.plan_service.list_benefits(plan.id)
            benefits_by_plan[plan.id] = [b.text for b in benefits]

        view = ShopView(plans, benefits_by_plan)
        await interaction.followup.send(embed=view.render_embed(), view=view, ephemeral=True)

    @app_commands.command(
        name="monetizacao", description="Abre o painel de configuração de Planos (Monetização)."
    )
    @is_admin()
    async def monetizacao(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=monetization_menu_embed(), view=MonetizationMenuView(), ephemeral=True
        )


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(ShopCog(bot))
