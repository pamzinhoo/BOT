from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from database.models.guild_settings import GuildSettings

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_CHANNEL = "channel"
_CATEGORY = "category"
_ROLE = "role"
_NUMBER = "number"

# (valor do select, rotulo, atributo em GuildSettings, tipo de campo)
_FIELDS: list[tuple[str, str, str, str]] = [
    ("log", "Canal de Logs", "log_channel_id", _CHANNEL),
    ("ranking", "Canal de Ranking", "ranking_channel_id", _CHANNEL),
    ("avaliacoes", "Canal de Avaliações", "evaluations_channel_id", _CHANNEL),
    ("alerta", "Canal de Alerta de Tickets", "ticket_alert_channel_id", _CHANNEL),
    ("transcricao", "Canal de Transcrições", "transcript_channel_id", _CHANNEL),
    ("dashboard", "Canal do Dashboard", "dashboard_channel_id", _CHANNEL),
    ("blacklist", "Canal de Blacklist (anti-spam)", "blacklist_channel_id", _CHANNEL),
    ("backup", "Canal de Backup Diário", "backup_channel_id", _CHANNEL),
    ("categoria", "Categoria de Tickets", "ticket_category_id", _CATEGORY),
    ("moderador", "Cargo Moderador", "moderator_role_id", _ROLE),
    ("dev", "Cargo Dev", "dev_role_id", _ROLE),
    ("ceo", "Cargo CEO", "ceo_role_id", _ROLE),
    ("inatividade", "Tempo de Inatividade (min)", "inactive_after_minutes", _NUMBER),
]
_FIELDS_BY_VALUE = {value: (label, attr, kind) for value, label, attr, kind in _FIELDS}


def config_summary_embed(settings: GuildSettings) -> discord.Embed:
    embed = discord.Embed(title="⚙️ Configuração do servidor")
    for _, label, attr, kind in _FIELDS:
        raw = getattr(settings, attr)
        if raw is None:
            display = "—"
        elif kind in (_CHANNEL, _CATEGORY):
            display = f"<#{raw}>"
        elif kind == _ROLE:
            display = f"<@&{raw}>"
        else:
            display = f"{raw} min"
        embed.add_field(name=label, value=display, inline=True)
    embed.set_footer(text="Selecione um item abaixo para editar.")
    return embed


async def _save_and_render(interaction: discord.Interaction, attr: str, value: int) -> None:
    assert interaction.guild_id is not None
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    fields: dict[str, Any] = {attr: value}
    if attr == "ranking_channel_id":
        fields["ranking_message_id"] = None
    await bot.config_service.update(interaction.guild_id, **fields)
    if attr in ("ranking_channel_id", "dashboard_channel_id"):
        await bot.painel_service.refresh_dashboard(interaction.guild_id)
    settings = await bot.config_service.get_settings(interaction.guild_id)
    await interaction.response.edit_message(
        content=None, embed=config_summary_embed(settings), view=ConfigPanelView()
    )


class _FieldPickSelect(discord.ui.Select["ConfigPanelView"]):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label=label, value=value) for value, label, _, _ in _FIELDS
        ]
        super().__init__(placeholder="O que deseja configurar?", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        label, attr, kind = _FIELDS_BY_VALUE[self.values[0]]

        if kind == _NUMBER:
            await interaction.response.send_modal(_NumberModal(attr, label))
            return

        picker_view = discord.ui.View(timeout=180)
        if kind == _CHANNEL:
            picker_view.add_item(
                _ChannelPicker(attr, label, [discord.ChannelType.text, discord.ChannelType.news])
            )
        elif kind == _CATEGORY:
            picker_view.add_item(_ChannelPicker(attr, label, [discord.ChannelType.category]))
        else:
            picker_view.add_item(_RolePicker(attr, label))
        picker_view.add_item(_BackButton())

        await interaction.response.edit_message(
            content=f"**{label}** — selecione abaixo:", embed=None, view=picker_view
        )


class _ChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, attr: str, label: str, channel_types: list[discord.ChannelType]) -> None:
        super().__init__(
            placeholder=f"Selecionar: {label}",
            channel_types=channel_types,
            min_values=1,
            max_values=1,
        )
        self.attr = attr

    async def callback(self, interaction: discord.Interaction) -> None:
        await _save_and_render(interaction, self.attr, self.values[0].id)


class _RolePicker(discord.ui.RoleSelect):
    def __init__(self, attr: str, label: str) -> None:
        super().__init__(placeholder=f"Selecionar: {label}", min_values=1, max_values=1)
        self.attr = attr

    async def callback(self, interaction: discord.Interaction) -> None:
        await _save_and_render(interaction, self.attr, self.values[0].id)


class _BackButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(label="Voltar", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        settings = await bot.config_service.get_settings(interaction.guild_id)
        await interaction.response.edit_message(
            content=None, embed=config_summary_embed(settings), view=ConfigPanelView()
        )


class _NumberModal(discord.ui.Modal):
    value_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Valor", placeholder="Ex: 15", required=True, max_length=5
    )

    def __init__(self, attr: str, label: str) -> None:
        super().__init__(title=label)
        self.attr = attr
        self.value_input.label = label

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.value_input.value).strip()
        if not raw.isdigit():
            await interaction.response.send_message("Digite um número inteiro válido.", ephemeral=True)
            return
        await _save_and_render(interaction, self.attr, int(raw))


class ConfigPanelView(discord.ui.View):
    """Painel interativo de configuração. Nao-persistente (timeout=300) —
    e um utilitario de admin aberto sob demanda, nao precisa sobreviver restart."""

    def __init__(self) -> None:
        super().__init__(timeout=300)
        self.add_item(_FieldPickSelect())
