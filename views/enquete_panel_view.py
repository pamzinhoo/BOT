from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

import discord

from database.models.enquete_settings import EnqueteSettings
from database.models.poll import VoteWeight
from utils.constants import EMBED_COLOR_DEFAULT
from views.base_view import SafeView
from views.settings_panel import (
    DomainSettingsView,
    FieldKind,
    SettingsField,
    build_domain_embed,
)

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_WEIGHT_MODE_CHOICES = [
    ("SNAPSHOT", "Fixo no momento do voto"),
    ("LIVE", "Atualiza se o cargo mudar"),
]

_ENQUETE_FIELDS = [
    SettingsField("enabled", "Sistema Ativado", FieldKind.BOOL, EnqueteSettings),
    SettingsField(
        "default_weight_mode", "Peso Padrão", FieldKind.CHOICE, EnqueteSettings, choices=_WEIGHT_MODE_CHOICES
    ),
    SettingsField("creation_message", "Mensagem de Criação", FieldKind.TEXT, EnqueteSettings),
    SettingsField("closing_message", "Mensagem de Encerramento", FieldKind.TEXT, EnqueteSettings),
    SettingsField("result_message", "Mensagem de Resultado", FieldKind.TEXT, EnqueteSettings),
]


def enquete_menu_embed() -> discord.Embed:
    return discord.Embed(
        title="🗳️ Enquetes",
        description=(
            "Sistema de enquetes com peso de voto por cargo. Configure o peso de cada "
            "cargo e as mensagens usadas nas enquetes criadas com /enquete criar."
        ),
        color=EMBED_COLOR_DEFAULT,
    )


class EnqueteMenuView(SafeView):
    def __init__(self, on_back: Any = None) -> None:
        super().__init__(timeout=300)
        self.on_back = on_back
        if on_back is not None:
            self.add_item(_BackToMainMenuButton(on_back))

    @discord.ui.button(label="⚙️ Configurações", style=discord.ButtonStyle.primary)
    async def settings_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]

        async def get_settings(guild_id: int) -> EnqueteSettings:
            return await bot.poll_service.get_settings(guild_id)

        view = DomainSettingsView(
            title="🗳️ Enquetes — Configurações",
            fields=_ENQUETE_FIELDS,
            get_settings=get_settings,
            update_settings=bot.poll_service.update_settings,
            on_back=functools.partial(_back_to_enquete_menu, self.on_back),
        )
        settings = await get_settings(interaction.guild_id)
        await interaction.response.edit_message(
            content=None, embed=build_domain_embed(view.title, view.fields, settings), view=view
        )

    @discord.ui.button(label="⚖️ Pesos de Voto", style=discord.ButtonStyle.secondary)
    async def weights_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        weights = await bot.vote_weight_service.get_weights(interaction.guild_id)
        await interaction.response.edit_message(
            content=None, embed=vote_weights_embed(weights), view=VoteWeightsListView(weights, self.on_back)
        )


async def _back_to_enquete_menu(on_back: Any, interaction: discord.Interaction) -> None:
    await interaction.response.edit_message(
        content=None, embed=enquete_menu_embed(), view=EnqueteMenuView(on_back=on_back)
    )


class _BackToMainMenuButton(discord.ui.Button[Any]):
    def __init__(self, on_back: Any) -> None:
        super().__init__(label="◀ Menu principal", style=discord.ButtonStyle.secondary, row=4)
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.on_back(interaction)


def vote_weights_embed(weights: list[VoteWeight]) -> discord.Embed:
    embed = discord.Embed(title="⚖️ Pesos de Voto", color=EMBED_COLOR_DEFAULT)
    if not weights:
        embed.description = "Nenhum peso configurado ainda — todo mundo vota com peso 1."
    else:
        for weight in weights:
            origem = "🔗 vindo de um plano" if weight.source == "PLAN_BENEFIT" else "✏️ manual"
            embed.add_field(
                name=f"<@&{weight.role_id}>", value=f"Peso **{weight.weight}** ({origem})", inline=True
            )
    return embed


class VoteWeightsListView(SafeView):
    def __init__(self, weights: list[VoteWeight], on_back: Any = None) -> None:
        super().__init__(timeout=300)
        self.weights = weights
        self.on_back = on_back
        self.add_item(_WeightRolePicker(on_back))
        if weights:
            self.add_item(_WeightDeleteSelect(weights, on_back))
        self.add_item(_BackToEnqueteMenuButton(on_back))


class _WeightRolePicker(discord.ui.RoleSelect):
    def __init__(self, on_back: Any) -> None:
        super().__init__(placeholder="Escolha um cargo pra definir o peso", min_values=1, max_values=1)
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(_WeightModal(self.values[0], self.on_back))


class _WeightModal(discord.ui.Modal, title="Definir peso de voto"):
    weight_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Peso (número inteiro maior que zero)", placeholder="Ex: 2", max_length=6
    )

    def __init__(self, role: discord.Role, on_back: Any = None) -> None:
        super().__init__()
        self.role = role
        self.on_back = on_back

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        raw = str(self.weight_input.value).strip()
        if not raw.isdigit() or int(raw) <= 0:
            await interaction.response.send_message(
                "Digite um número inteiro maior que zero.", ephemeral=True
            )
            return
        await bot.vote_weight_service.set_weight(interaction.guild_id, self.role.id, int(raw))
        weights = await bot.vote_weight_service.get_weights(interaction.guild_id)
        await interaction.response.edit_message(
            content=None, embed=vote_weights_embed(weights), view=VoteWeightsListView(weights, self.on_back)
        )


class _WeightDeleteSelect(discord.ui.Select[Any]):
    def __init__(self, weights: list[VoteWeight], on_back: Any = None) -> None:
        options = [
            discord.SelectOption(label=f"Remover peso do cargo {w.role_id}", value=str(w.role_id))
            for w in weights
        ][:25]
        super().__init__(placeholder="Remover um peso existente...", options=options, min_values=1, max_values=1)
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        await bot.vote_weight_service.delete_weight(interaction.guild_id, int(self.values[0]))
        weights = await bot.vote_weight_service.get_weights(interaction.guild_id)
        await interaction.response.edit_message(
            content=None, embed=vote_weights_embed(weights), view=VoteWeightsListView(weights, self.on_back)
        )


class _BackToEnqueteMenuButton(discord.ui.Button[Any]):
    def __init__(self, on_back: Any = None) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary)
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await _back_to_enquete_menu(self.on_back, interaction)
