from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import LimerenceBot
from utils.checks import is_admin
from utils.constants import EMBED_COLOR_DEFAULT


class SubscriptionsCog(commands.Cog):
    """Consulta/gestao de assinaturas de Planos — regra de negocio inteira
    vive em SubscriptionService, esta Cog so recebe comandos."""

    assinatura_group = app_commands.Group(
        name="assinatura", description="Gerencia sua assinatura de Planos neste servidor."
    )

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    @assinatura_group.command(name="ver", description="Mostra suas assinaturas ativas neste servidor.")
    async def ver(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        # Defere de imediato: list_active_subscriptions + o laco de get_plan
        # abaixo sao varias chamadas ao banco que podem passar dos 3s de
        # prazo do Discord antes da 1a resposta.
        await interaction.response.defer(ephemeral=True)
        subscriptions = await self.bot.subscription_service.list_active_subscriptions(
            interaction.guild_id, interaction.user.id
        )
        if not subscriptions:
            await interaction.followup.send("Você não tem nenhuma assinatura ativa.", ephemeral=True)
            return

        embed = discord.Embed(title="📦 Suas assinaturas", color=EMBED_COLOR_DEFAULT)
        for subscription in subscriptions:
            plan = await self.bot.plan_service.get_plan(subscription.plan_id)
            name = plan.name if plan is not None else "Plano removido"
            renew = (
                subscription.current_period_end.strftime("%d/%m/%Y")
                if subscription.current_period_end
                else "sem renovação"
            )
            embed.add_field(name=name, value=f"Válido até: {renew}", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @assinatura_group.command(name="cancelar", description="Cancela a assinatura de um usuário (staff).")
    @app_commands.describe(usuario="Usuário cuja assinatura será cancelada")
    @is_admin()
    async def cancelar(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        assert interaction.guild_id is not None
        # Defere de imediato: list_cancelable_subscriptions + o laco de
        # cancel_subscription abaixo sao varias chamadas ao banco que podem
        # passar dos 3s de prazo do Discord antes da 1a resposta.
        await interaction.response.defer(ephemeral=True)
        subscriptions = await self.bot.subscription_service.list_cancelable_subscriptions(
            interaction.guild_id, usuario.id
        )
        if not subscriptions:
            await interaction.followup.send(
                "Este usuário não tem assinaturas ativas ou pendentes.", ephemeral=True
            )
            return
        for subscription in subscriptions:
            await self.bot.subscription_service.cancel_subscription(
                subscription.id, executor=interaction.user
            )
        await interaction.followup.send(
            f"Assinatura(s) de {usuario.mention} cancelada(s).", ephemeral=True
        )


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(SubscriptionsCog(bot))
