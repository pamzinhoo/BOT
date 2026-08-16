from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from database.models.ticket_panel import TicketPanel
from database.models.ticket_panel_form_field import TicketPanelFormField
from services.ticket_panel_service import (
    button_style_from_value,
    chunk_panels_for_selects,
    normalize_selection_mode,
    selectable_panels,
)
from views.base_view import SafeView

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_CUSTOM_ID_PREFIX = "limerence:ticket_panel:"

CATEGORY_SELECT_PLACEHOLDER = "📋 Selecionar categoria"


def open_button_custom_id(key: str) -> str:
    return f"{_CUSTOM_ID_PREFIX}{key}:open"


def category_select_custom_id(index: int) -> str:
    """Um custom_id por bloco de 25 categorias. Nao carrega guild nem painel:
    a `key` escolhida vem no proprio valor da opcao e a config e relida do
    banco a cada clique, igual acontece no modo de botoes."""
    return f"{_CUSTOM_ID_PREFIX}select:{index}"


def panel_select_option(panel: TicketPanel) -> discord.SelectOption:
    """Opcao do select montada 100% da config real do painel — nada de
    categoria hardcoded. `value` e a `key` do painel (slug estavel)."""
    description = " ".join((panel.embed_description or "").split()) or None
    return discord.SelectOption(
        label=(panel.button_label or panel.name)[:100],
        value=panel.key,
        description=description[:100] if description else None,
        emoji=panel.button_emoji or None,
    )


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

        await _handle_open_click(interaction, panel)


class _OpenTicketSelect(discord.ui.Select[Any]):
    """Lista suspensa com uma opcao por categoria (painel) do combo. Substitui
    os botoes quando `ticket_settings.category_selection_mode == "select"`.

    Reaproveita exatamente o mesmo caminho do botao (`_handle_open_click`):
    formulario, mensagem intermediaria, limites, permissoes, aprovacao e
    criacao do canal continuam sendo os do painel escolhido."""

    def __init__(self, panels: list[TicketPanel], index: int = 0) -> None:
        super().__init__(
            placeholder=CATEGORY_SELECT_PLACEHOLDER,
            options=[panel_select_option(panel) for panel in panels],
            min_values=1,
            max_values=1,
            custom_id=category_select_custom_id(index),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Este painel só funciona dentro de um servidor.", ephemeral=True
            )
            return

        panel = await bot.ticket_panel_service.get_panel_by_key(
            interaction.guild_id, self.values[0]
        )
        if panel is None:
            await interaction.response.send_message(
                "Essa categoria não existe mais. Avise um administrador.", ephemeral=True
            )
            return

        await _handle_open_click(interaction, panel)


async def _handle_open_click(interaction: discord.Interaction, panel: TicketPanel) -> None:
    """Compartilhado entre o botao de categoria e o botao de continuar da
    mensagem intermediaria. Decide ANTES de gastar qualquer round-trip extra
    no banco se vai precisar mostrar modal — modal so pode ser a primeira
    resposta da interaction (regra do Discord), entao nesse caso não da pra
    `defer()` antes. Fora esse caso, defere na hora pra nunca estourar os 3s
    do Discord esperando o Supabase responder (raiz do erro "nao respondeu a
    tempo" — antes disso o codigo fazia 2+ queries seriais antes de responder
    de qualquer jeito)."""
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]

    fields = (
        await bot.ticket_panel_service.list_form_fields(panel.id) if panel.form_enabled else []
    )
    if fields:
        # check_can_open eh refeito dentro de open_ticket() no on_submit do
        # modal — nao precisa (nem da, sem deferir primeiro) checar aqui.
        await interaction.response.send_modal(TicketPanelFormModal(panel, fields))
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    blocked = await bot.ticket_panel_service.check_can_open(
        interaction.guild_id, interaction.user.id, panel
    )
    if blocked is not None:
        await interaction.followup.send(blocked, ephemeral=True)
        return

    if panel.intro_enabled:
        view = SafeView(timeout=300)
        view.add_item(_IntroContinueButton(panel))
        await interaction.followup.send(
            content=panel.intro_message or "​",
            view=view,
            ephemeral=True,
        )
        return

    await bot.ticket_panel_service.open_ticket(interaction, panel)


class _IntroContinueButton(discord.ui.Button[Any]):
    """Segundo botao, mostrado so depois da mensagem intermediaria — reavalia
    tudo de novo porque pode ter passado tempo entre os dois cliques."""

    def __init__(self, panel: TicketPanel) -> None:
        super().__init__(
            label=(panel.intro_button_label or "Abrir Ticket")[:80],
            emoji=panel.intro_button_emoji or None,
            style=button_style_from_value(panel.intro_button_style),
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

        await _handle_open_click(interaction, panel)


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
        if panel.show_button:
            self.add_item(_OpenTicketButton(panel))


class TicketPanelGroupOpenView(SafeView):
    """View persistente com as categorias (paineis) de um combo — mesma embed
    unica (do painel principal) e, ao lado dela, um botao por categoria OU uma
    lista suspensa com todas, conforme
    `ticket_settings.category_selection_mode`.

    Nos dois modos a categoria e o mesmo painel: custom_id, permissao,
    formulario, aprovacao e comportamento seguem 100% da config daquele painel,
    sem duplicar logica. Paineis com `show_button=False` (ex.: o principal, so
    pra dar embed pro combo) nao viram botao nem opcao.

    Se houver mais categorias do que cabe num select (25), elas sao repartidas
    em ate 5 selects — nenhuma categoria some por conta propria (o excedente
    alem disso e barrado na publicacao, ver `panels_over_capacity`)."""

    def __init__(self, panels: list[TicketPanel], mode: str | None = None) -> None:
        super().__init__(timeout=None)
        visible = selectable_panels(panels)
        if normalize_selection_mode(mode) == "select":
            for index, chunk in enumerate(chunk_panels_for_selects(visible)):
                self.add_item(_OpenTicketSelect(chunk, index))
            return
        for panel in visible:
            self.add_item(_OpenTicketButton(panel))
