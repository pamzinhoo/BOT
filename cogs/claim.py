from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import LimerenceBot
from database.models.log import LogAction
from services.claim_service import ClaimError
from services.ticket_panel_service import member_matches_panel_claim_roles
from utils.checks import has_permission


class ClaimCog(commands.Cog):
    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    @app_commands.command(name="claim", description="Assume o ticket deste canal.")
    @has_permission("claim")
    async def claim(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member) or interaction.channel_id is None:
            return

        existing = await self.bot.ticket_service.get_by_channel_id(interaction.channel_id)
        panel = await self.bot.ticket_panel_service.get_panel_for_ticket(existing) if existing else None
        if not member_matches_panel_claim_roles(member, panel):
            await interaction.response.send_message(
                "Apenas os cargos responsáveis por este painel podem assumir este ticket.",
                ephemeral=True,
            )
            return

        staff = await self.bot.staff_service.ensure_staff(guild.id, member.id, member.display_name)
        try:
            await self.bot.claim_service.claim_ticket(interaction.channel_id, staff.id)
        except ClaimError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        ticket = await self.bot.ticket_service.get_by_channel_id(interaction.channel_id)
        await self.bot.log_service.record(
            guild_id=guild.id,
            action=LogAction.CLAIM,
            actor_discord_id=member.id,
            staff_id=staff.id,
            ticket_id=ticket.id if ticket else None,
            category_snapshot=ticket.category.value if ticket else None,
            message=f"{member} assumiu o ticket via /claim.",
        )
        await self.bot.painel_service.refresh_dashboard(guild.id)
        await interaction.response.send_message(f"{member.mention} assumiu este ticket.")

    @app_commands.command(name="unclaim", description="Libera o ticket deste canal.")
    @has_permission("unclaim")
    async def unclaim(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member) or interaction.channel_id is None:
            return

        staff = await self.bot.staff_service.ensure_staff(guild.id, member.id, member.display_name)
        try:
            await self.bot.claim_service.unclaim_ticket(interaction.channel_id, staff.id)
        except ClaimError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        ticket = await self.bot.ticket_service.get_by_channel_id(interaction.channel_id)
        await self.bot.log_service.record(
            guild_id=guild.id,
            action=LogAction.UNCLAIM,
            actor_discord_id=member.id,
            staff_id=staff.id,
            ticket_id=ticket.id if ticket else None,
            category_snapshot=ticket.category.value if ticket else None,
            message=f"{member} liberou o ticket via /unclaim.",
        )
        await self.bot.painel_service.refresh_dashboard(guild.id)
        await interaction.response.send_message(f"{member.mention} liberou este ticket.")


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(ClaimCog(bot))
