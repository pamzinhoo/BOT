from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from services.ticket_panel_service import (
    TicketPanelError,
    member_matches_panel_claim_roles,
)
from utils.checks import member_can
from views.base_view import SafeView

if TYPE_CHECKING:
    from core.bot import LimerenceBot


async def _deny_if_cant_review(interaction: discord.Interaction) -> bool:
    """Mesma regra do botao Assumir: permissao global de `claim` + o filtro
    extra de cargos do painel (panel.claim_role_ids), quando configurado."""
    if not isinstance(interaction.user, discord.Member) or interaction.channel_id is None:
        await interaction.response.send_message(
            "Este botão só funciona dentro de um servidor.", ephemeral=True
        )
        return True
    if not await member_can(interaction, "claim"):
        await interaction.response.send_message(
            "Você não tem permissão para analisar este ticket.", ephemeral=True
        )
        return True

    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    ticket = await bot.ticket_panel_service.get_ticket_by_channel(interaction.channel_id)
    panel = await bot.ticket_panel_service.get_panel_for_ticket(ticket) if ticket else None
    if not member_matches_panel_claim_roles(interaction.user, panel):
        await interaction.response.send_message(
            "Apenas os cargos responsáveis por este painel podem analisar o ticket.",
            ephemeral=True,
        )
        return True
    return False


async def _finish(interaction: discord.Interaction, *, approved: bool, reason: str | None) -> None:
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    try:
        message = await bot.ticket_panel_service.review_ticket(
            interaction, approved=approved, reason=reason
        )
    except TicketPanelError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return

    if isinstance(interaction.message, discord.Message):
        disabled_view = TicketApprovalView()
        for item in disabled_view.children:
            item.disabled = True  # type: ignore[attr-defined]
        try:
            await interaction.message.edit(view=disabled_view)
        except discord.HTTPException:
            pass
    await interaction.followup.send(message, ephemeral=False)


class _ReproveReasonModal(discord.ui.Modal, title="Reprovar solicitação"):
    reason_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Motivo (enviado por DM ao autor)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await _finish(
            interaction, approved=False, reason=str(self.reason_input.value).strip() or None
        )


class TicketApprovalView(SafeView):
    """Botoes Aprovar/Reprovar dos tickets vindos de um painel com etapa de
    aprovacao. Persistent (timeout=None) e sem id no custom_id — resolve o
    ticket pelo channel_id da interacao, igual TicketActionsView.

    Fica numa mensagem separada da TicketActionsView: aprovar/reprovar NAO
    substitui assumir/fechar, o ticket continua sendo um ticket normal."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Aprovar",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="limerence:ticket_approval:approve",
    )
    async def approve(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if await _deny_if_cant_review(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await _finish(interaction, approved=True, reason=None)

    @discord.ui.button(
        label="Reprovar",
        style=discord.ButtonStyle.danger,
        emoji="❌",
        custom_id="limerence:ticket_approval:reprove",
    )
    async def reprove(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if await _deny_if_cant_review(interaction):
            return
        await interaction.response.send_modal(_ReproveReasonModal())
