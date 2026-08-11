from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from database.models.ticket_panel import TicketPanel
from database.models.ticket_panel_form_field import TicketPanelFormField
from services.ticket_panel_service import button_style_from_value
from views.base_view import SafeView

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_CUSTOM_ID_PREFIX = "limerence:ticket_panel:"


def open_button_custom_id(key: str) -> str:
    return f"{_CUSTOM_ID_PREFIX}{key}:open"


class _OpenTicketButton(discord.ui.Button[Any]):
    """Botao de abrir ticket de UM painel. O custom_id carrega so a `key` do
    painel (estavel, nunca muda) — a guild vem da propria interaction e a
    config e relida do banco a cada clique, entao editar o painel no /config
    ja reflete no proximo clique sem precisar republicar."""

    def __init__(self, panel: TicketPanel) -> None:
        super().__init__(
            label=(panel.button_label or f"Abrir {panel.name}")[:80],
            emoji=panel.button_emoji or None,
            style=button_style_from_value(panel.button_style),
            custom_id=open_button_custom_id(panel.key),
        )
        self.panel_key = panel.key

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Este painel só funciona dentro de um servidor.", ephemeral=True
            )
            return

        panel = await bot.ticket_panel_service.get_panel_by_key(
            interaction.guild_id, self.panel_key
        )
        if panel is None:
            await interaction.response.send_message(
                "Este painel não existe mais. Avise um administrador.", ephemeral=True
            )
            return

        blocked = await bot.ticket_panel_service.check_can_open(
            interaction.guild_id, interaction.user.id, panel
        )
        if blocked is not None:
            await interaction.response.send_message(blocked, ephemeral=True)
            return

        fields = (
            await bot.ticket_panel_service.list_form_fields(panel.id)
            if panel.form_enabled
            else []
        )
        if fields:
            await interaction.response.send_modal(TicketPanelFormModal(panel, fields))
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        await bot.ticket_panel_service.open_ticket(interaction, panel)


class TicketPanelFormModal(discord.ui.Modal):
    """Modal montado em tempo de execucao com as perguntas cadastradas no painel
    (no maximo 5 — limite do Discord, garantido no service)."""

    def __init__(self, panel: TicketPanel, fields: list[TicketPanelFormField]) -> None:
        super().__init__(title=f"{panel.name}"[:45], timeout=600)
        self.panel = panel
        self.inputs: list[tuple[str, discord.ui.TextInput[Any]]] = []
        for field in fields[:5]:
            text_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
                label=field.label[:45],
                style=(
                    discord.TextStyle.paragraph
                    if field.style == "long"
                    else discord.TextStyle.short
                ),
                required=field.required,
                placeholder=field.placeholder or None,
                max_length=1000 if field.style == "long" else 200,
            )
            self.add_item(text_input)
            self.inputs.append((field.label, text_input))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        await interaction.response.defer(ephemeral=True, thinking=True)
        answers = [(label, str(item.value or "").strip()) for label, item in self.inputs]
        await bot.ticket_panel_service.open_ticket(interaction, self.panel, answers=answers)


class TicketPanelOpenView(SafeView):
    """View persistente (timeout=None) publicada junto com a embed do painel.
    Uma instancia por painel — registrada no boot pra todos os paineis ja
    publicados (ver LimerenceBot._register_persistent_views)."""

    def __init__(self, panel: TicketPanel) -> None:
        super().__init__(timeout=None)
        self.add_item(_OpenTicketButton(panel))


class TicketPanelGroupOpenView(SafeView):
    """View persistente com UM botao de abrir ticket por painel do combo —
    mesma embed unica (do painel principal), varios botoes lado a lado (ex.:
    "Suporte" + "Denuncia"). Cada botao continua sendo o mesmo
    `_OpenTicketButton` do painel individual: custom_id, permissao, formulario
    e aprovacao seguem 100% da config daquele painel, sem duplicar logica."""

    def __init__(self, panels: list[TicketPanel]) -> None:
        super().__init__(timeout=None)
        for panel in panels:
            self.add_item(_OpenTicketButton(panel))
