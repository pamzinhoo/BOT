from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from views.base_view import SafeView

from database.models.ticket import TicketCategory
from services.ticket_panel_service import SYSTEM_DISABLED_MESSAGE
from utils.constants import CATEGORY_LABELS, EMBED_COLOR_WARNING
from views.embeds import (
    category_confirm_embed,
    category_from_value,
    category_select_options,
    ticket_embed,
)
from views.ticket_actions_view import TicketActionsView

if TYPE_CHECKING:
    from core.bot import LimerenceBot


async def _create_ticket(interaction: discord.Interaction, category: TicketCategory) -> None:
    guild = interaction.guild
    member = interaction.user
    if guild is None or not isinstance(member, discord.Member):
        await interaction.followup.send(
            "Este painel só funciona dentro de um servidor.", ephemeral=True
        )
        return

    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    settings = await bot.config_service.get_settings(guild.id)
    ticket_settings = await bot.config_service.get_ticket_settings(guild.id)

    # kill switch global do sistema de tickets — vale tambem pro painel legado.
    # Tickets ja abertos continuam funcionando; so a abertura fica bloqueada.
    if not ticket_settings.enabled:
        await interaction.followup.send(SYSTEM_DISABLED_MESSAGE, ephemeral=True)
        return

    open_count = await bot.ticket_service.count_open_by_member(guild.id, member.id)
    if not ticket_settings.allow_multiple_tickets and open_count >= 1:
        await interaction.followup.send(
            "Você já tem um ticket aberto. Feche-o antes de abrir outro.", ephemeral=True
        )
        return
    if (
        ticket_settings.max_tickets_per_user is not None
        and open_count >= ticket_settings.max_tickets_per_user
    ):
        await interaction.followup.send(
            f"Você atingiu o limite de {ticket_settings.max_tickets_per_user} tickets abertos.",
            ephemeral=True,
        )
        return

    category_channel = None
    if settings.ticket_category_id is not None:
        channel = guild.get_channel(settings.ticket_category_id)
        if isinstance(channel, discord.CategoryChannel):
            category_channel = channel

    staff_role_ids = [
        role_id
        for role_id in (settings.moderator_role_id, settings.dev_role_id, settings.ceo_role_id)
        if role_id is not None
    ]

    try:
        ticket, ticket_channel = await bot.ticket_service.create_ticket(
            guild, member, category, category_channel, staff_role_ids
        )
    except discord.HTTPException:
        await interaction.followup.send(
            "Não foi possível criar o canal do ticket. Tente novamente mais tarde.",
            ephemeral=True,
        )
        return

    await ticket_channel.send(
        content=member.mention, embed=ticket_embed(ticket, member), view=TicketActionsView()
    )
    await interaction.followup.send(f"Seu ticket foi criado: {ticket_channel.mention}", ephemeral=True)

    if settings.ticket_alert_channel_id is not None:
        alert_channel = guild.get_channel(settings.ticket_alert_channel_id)
        if isinstance(alert_channel, discord.TextChannel):
            role_mentions = " ".join(f"<@&{role_id}>" for role_id in staff_role_ids)
            embed = discord.Embed(
                title="🔔 Novo ticket aberto",
                description=(
                    f"{CATEGORY_LABELS[category]} · aberto por {member.mention}\n"
                    f"Canal: {ticket_channel.mention}"
                ),
                color=EMBED_COLOR_WARNING,
            )
            await alert_channel.send(content=role_mentions or None, embed=embed)


class _ConfirmOpenTicketView(SafeView):
    """Confirmacao ephemera antes de criar o canal — mostra o aviso da categoria."""

    def __init__(self, category: TicketCategory) -> None:
        super().__init__(timeout=120)
        self.category = category

    @discord.ui.button(label="Confirmar e abrir ticket", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(view=self)
        await _create_ticket(interaction, self.category)
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(
            content="Abertura de ticket cancelada.", embed=None, view=self
        )
        self.stop()


class _CategorySelect(discord.ui.Select["PainelView"]):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Selecione uma categoria para abrir um ticket...",
            options=category_select_options(),
            custom_id="limerence:painel:category_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        category = category_from_value(self.values[0])
        await interaction.response.send_message(
            embed=category_confirm_embed(category),
            view=_ConfirmOpenTicketView(category),
            ephemeral=True,
        )


class PainelView(SafeView):
    """Painel fixo com dropdown de categoria pra abrir tickets. Persistent (timeout=None)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(_CategorySelect())
