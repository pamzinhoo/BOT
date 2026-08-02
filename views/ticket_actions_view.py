from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from views.base_view import SafeView

from database.models.log import LogAction
from database.models.ticket import TicketStatus
from services.claim_service import ClaimError
from services.ticket_panel_service import member_matches_panel_claim_roles
from services.ticket_service import TicketNotClaimedError, TicketNotFoundError
from utils.achievements import announce_achievements
from utils.checks import member_can, member_is_staff
from utils.constants import EMBED_COLOR_DANGER
from views.confirm_close_view import ConfirmCloseView
from views.evaluation_view import EvaluationView
from views.ticket_closed_view import TicketClosedView

if TYPE_CHECKING:
    from core.bot import LimerenceBot


async def _deny_if_cant(interaction: discord.Interaction, action: str) -> bool:
    if await member_can(interaction, action):
        return False
    await interaction.response.send_message(
        "Você não tem permissão para usar esse botão.", ephemeral=True
    )
    return True


class TicketActionsView(SafeView):
    """Botoes Assumir/Liberar/Fechar. Staff-only. Persistent (timeout=None),
    resolve o ticket pelo channel_id da interacao — nenhum dado sensivel no
    custom_id."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Assumir", style=discord.ButtonStyle.success, custom_id="limerence:ticket:claim"
    )
    async def claim(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if await _deny_if_cant(interaction, "claim"):
            return
        await interaction.response.defer(ephemeral=True)
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member) or interaction.channel_id is None:
            return

        # filtro extra por painel: se o painel que originou o ticket restringiu
        # os cargos que podem assumir, ele vale POR CIMA da permissao global de
        # `claim` (nunca no lugar dela). Ticket sem painel = nada muda.
        existing = await bot.ticket_service.get_by_channel_id(interaction.channel_id)
        panel = await bot.ticket_panel_service.get_panel_for_ticket(existing) if existing else None
        if not member_matches_panel_claim_roles(member, panel):
            await interaction.followup.send(
                "Apenas os cargos responsáveis por este painel podem assumir este ticket.",
                ephemeral=True,
            )
            return

        staff = await bot.staff_service.ensure_staff(guild.id, member.id, member.display_name)
        try:
            await bot.claim_service.claim_ticket(interaction.channel_id, staff.id)
        except ClaimError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        ticket = await bot.ticket_service.get_by_channel_id(interaction.channel_id)
        await bot.log_service.record(
            guild_id=guild.id,
            action=LogAction.CLAIM,
            actor_discord_id=member.id,
            staff_id=staff.id,
            ticket_id=ticket.id if ticket else None,
            category_snapshot=ticket.category.value if ticket else None,
            message=f"{member} assumiu o ticket.",
        )
        await bot.painel_service.refresh_dashboard(guild.id)
        await interaction.followup.send(f"{member.mention} assumiu este ticket.", ephemeral=False)

    @discord.ui.button(
        label="Liberar", style=discord.ButtonStyle.secondary, custom_id="limerence:ticket:unclaim"
    )
    async def unclaim(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if await _deny_if_cant(interaction, "unclaim"):
            return
        await interaction.response.defer(ephemeral=True)
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member) or interaction.channel_id is None:
            return

        staff = await bot.staff_service.ensure_staff(guild.id, member.id, member.display_name)
        try:
            await bot.claim_service.unclaim_ticket(interaction.channel_id, staff.id)
        except ClaimError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        ticket = await bot.ticket_service.get_by_channel_id(interaction.channel_id)
        await bot.log_service.record(
            guild_id=guild.id,
            action=LogAction.UNCLAIM,
            actor_discord_id=member.id,
            staff_id=staff.id,
            ticket_id=ticket.id if ticket else None,
            category_snapshot=ticket.category.value if ticket else None,
            message=f"{member} liberou o ticket.",
        )
        await bot.painel_service.refresh_dashboard(guild.id)
        await interaction.followup.send(f"{member.mention} liberou este ticket.", ephemeral=False)

    @discord.ui.button(
        label="Criar Canal de Voz",
        style=discord.ButtonStyle.secondary,
        custom_id="limerence:ticket:voice",
        emoji="🔊",
    )
    async def create_voice_channel(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        if not await member_is_staff(interaction):
            await interaction.response.send_message(
                "Apenas a staff pode usar esse botão.", ephemeral=True
            )
            return
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        guild = interaction.guild
        member = interaction.user
        channel = interaction.channel
        if (
            guild is None
            or not isinstance(member, discord.Member)
            or interaction.channel_id is None
            or not isinstance(channel, discord.TextChannel)
        ):
            return

        ticket = await bot.ticket_service.get_by_channel_id(interaction.channel_id)
        if ticket is None:
            await interaction.response.send_message("Ticket não encontrado.", ephemeral=True)
            return

        if ticket.voice_channel_id is not None:
            existing = guild.get_channel(ticket.voice_channel_id)
            if isinstance(existing, discord.VoiceChannel):
                await interaction.response.send_message(
                    f"Já existe um canal de voz para este ticket: {existing.mention}",
                    ephemeral=True,
                )
                return

        settings = await bot.config_service.get_settings(guild.id)
        staff_role_ids = [
            role_id
            for role_id in (settings.moderator_role_id, settings.dev_role_id, settings.ceo_role_id)
            if role_id is not None
        ]

        opener = guild.get_member(ticket.opened_by_discord_id)
        overwrites: dict[
            discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite
        ] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
        }
        if opener is not None:
            overwrites[opener] = discord.PermissionOverwrite(
                view_channel=True, connect=True, speak=True
            )
        for role_id in staff_role_ids:
            role = guild.get_role(role_id)
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, connect=True, speak=True
                )

        try:
            voice_channel = await guild.create_voice_channel(
                name=f"voz-{channel.name}"[:90],
                category=channel.category,
                overwrites=overwrites,
                reason=f"Canal de voz do ticket criado por {member}",
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "Não foi possível criar o canal de voz. Tente novamente mais tarde.",
                ephemeral=True,
            )
            return

        await bot.ticket_service.set_voice_channel(interaction.channel_id, voice_channel.id)
        await interaction.response.send_message(
            f"Canal de voz criado: {voice_channel.mention}", ephemeral=False
        )

    @discord.ui.button(
        label="Fechar", style=discord.ButtonStyle.danger, custom_id="limerence:ticket:close"
    )
    async def close(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if await _deny_if_cant(interaction, "fechar"):
            return
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member) or interaction.channel_id is None:
            return

        existing_ticket = await bot.ticket_service.get_by_channel_id(interaction.channel_id)
        if existing_ticket is None:
            await interaction.response.send_message("Ticket não encontrado.", ephemeral=True)
            return
        if existing_ticket.claimed_by_staff_id is None:
            await interaction.response.send_message(
                "Este ticket ainda não foi assumido por ninguém. Clique em **Assumir** antes de fechar.",
                ephemeral=True,
            )
            return

        confirm_view = ConfirmCloseView(member.id)
        await interaction.response.send_message(
            "Tem certeza que deseja fechar este ticket?", view=confirm_view, ephemeral=True
        )
        await confirm_view.wait()
        if not confirm_view.confirmed:
            return

        try:
            result = await bot.ticket_service.close_ticket(interaction.channel_id, member.id)
        except (TicketNotFoundError, TicketNotClaimedError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        ticket = result.ticket

        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        if isinstance(interaction.message, discord.Message):
            await interaction.message.edit(view=self)

        await bot.log_service.record(
            guild_id=guild.id,
            action=LogAction.FECHAMENTO,
            actor_discord_id=member.id,
            ticket_id=ticket.id,
            category_snapshot=ticket.category.value,
            message=f"{member} fechou o ticket.",
        )
        await bot.painel_service.refresh_dashboard(guild.id)

        if ticket.voice_channel_id is not None:
            voice_channel = guild.get_channel(ticket.voice_channel_id)
            if isinstance(voice_channel, discord.VoiceChannel):
                try:
                    await voice_channel.delete(reason="Ticket fechado.")
                except discord.HTTPException:
                    pass

        channel = interaction.channel
        if ticket.status == TicketStatus.CLOSED and isinstance(channel, discord.TextChannel):
            await channel.send(
                embed=discord.Embed(
                    title="✅ Ticket fechado",
                    description=f"Fechado por {member.mention}.",
                    color=EMBED_COLOR_DANGER,
                ),
                view=TicketClosedView(),
            )
            if ticket.claimed_by_staff_id is not None:
                await announce_achievements(
                    bot, channel, ticket.claimed_by_staff_id, result.unlocked_achievements
                )
            opener = guild.get_member(ticket.opened_by_discord_id)
            eval_settings = await bot.config_service.get_evaluation_settings(guild.id)
            behaviour = await bot.ticket_panel_service.behaviour_for_ticket(ticket, guild.id)
            if opener is not None and eval_settings.enabled and behaviour.evaluation_enabled:
                await channel.send(
                    content=opener.mention,
                    embed=discord.Embed(
                        title="Como foi o seu atendimento?",
                        description="Avalie o suporte que você recebeu.",
                    ),
                    view=EvaluationView(),
                )
