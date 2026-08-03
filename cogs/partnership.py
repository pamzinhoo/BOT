from __future__ import annotations

from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import LimerenceBot
from services.partnership_service import (
    PartnershipCooldownError,
    PartnershipError,
    cooldown_remaining,
    member_has_role,
)
from views.embeds import partnership_status_embed
from views.partnership_view import PartnershipPublishModal


class PartnershipCog(commands.Cog):
    parceria_group = app_commands.Group(
        name="parceria", description="Sistema de parcerias/streamers do servidor."
    )

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    @parceria_group.command(name="publicar", description="Publica ou atualiza a divulgação da sua parceria.")
    async def publicar(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return

        settings = await self.bot.partnership_service.get_settings(guild.id)
        if not settings.enabled:
            await interaction.response.send_message(
                "O sistema de parcerias está desativado neste servidor.", ephemeral=True
            )
            return
        if not member_has_role(member, settings.partner_role_id):
            await interaction.response.send_message(
                "Você não possui o cargo necessário para publicar uma parceria.", ephemeral=True
            )
            return

        partnership = await self.bot.partnership_service.get_partnership(guild.id, member.id)
        if partnership is not None:
            remaining = cooldown_remaining(settings.cooldown_hours, partnership.last_publish_at, datetime.now(UTC))
            if remaining is not None:
                error = PartnershipCooldownError(remaining)
                await interaction.response.send_message(f"⏳ {error}", ephemeral=True)
                return

        await interaction.response.send_modal(PartnershipPublishModal(settings))

    @parceria_group.command(name="status", description="Mostra o status da sua parceria.")
    async def status(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        settings = await self.bot.partnership_service.get_settings(guild.id)
        partnership = await self.bot.partnership_service.get_partnership(guild.id, interaction.user.id)
        await interaction.response.send_message(
            embed=partnership_status_embed(partnership, settings, now=datetime.now(UTC)), ephemeral=True
        )

    @parceria_group.command(name="remover", description="Remove uma parceria (somente staff).")
    @app_commands.describe(
        parceiro="Dono da parceria a remover (padrão: a parceria vinculada a este canal/tópico)"
    )
    async def remover(
        self, interaction: discord.Interaction, parceiro: discord.Member | None = None
    ) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            record = await self.bot.partnership_service.remove(
                guild=guild,
                actor=member,
                owner=parceiro,
                channel_id=interaction.channel_id if parceiro is None else None,
            )
        except PartnershipError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

        await interaction.followup.send(f"🗑️ Parceria de **{record.name}** removida.", ephemeral=True)


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(PartnershipCog(bot))
