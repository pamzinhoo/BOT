from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from utils.checks import member_is_admin, member_is_staff
from utils.constants import HELP_CATEGORIES, HELP_CATEGORY_LABELS
from views.base_view import SafeView
from views.embeds import help_category_embed, help_general_embed, help_main_embed

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_EXCLUDED_QUALIFIED_NAMES = {"config painel"}


def _all_commands(bot: LimerenceBot, guild: discord.abc.Snowflake | None) -> list[tuple[str, str]]:
    """Todos os slash commands registrados na tree (inclusive subcomandos de
    grupo), em ordem alfabetica pelo nome completo. /config painel fica de
    fora — o resto de /config aparece normalmente.

    Com TEST_GUILD_ID configurado, core/bot.py::setup_hook copia os comandos
    globais pra guild de teste e depois limpa a tree global local (so pra nao
    duplicar no Discord) — entao walk_commands() sem guild fica vazio nesse
    modo. Junta os dois: guild-scoped primeiro, global como complemento."""
    seen: dict[str, app_commands.Command] = {}
    if guild is not None:
        for command in bot.tree.walk_commands(guild=guild):
            seen[command.qualified_name] = command
    for command in bot.tree.walk_commands():
        seen.setdefault(command.qualified_name, command)

    commands = [
        (name, command.description)
        for name, command in seen.items()
        if name not in _EXCLUDED_QUALIFIED_NAMES
    ]
    commands.sort(key=lambda item: item[0])
    return commands


async def _open_category(interaction: discord.Interaction, category: str) -> None:
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    is_admin = await member_is_admin(interaction)
    is_staff = await member_is_staff(interaction)
    commands = await bot.help_service.list_visible_by_category(
        category, is_admin=is_admin, is_staff=is_staff
    )
    await interaction.response.edit_message(
        embed=help_category_embed(category, commands), view=HelpCategoryView()
    )


async def _open_general(interaction: discord.Interaction) -> None:
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    await interaction.response.edit_message(
        embed=help_general_embed(_all_commands(bot, interaction.guild)), view=HelpCategoryView()
    )


async def _back_to_main_menu(interaction: discord.Interaction) -> None:
    await interaction.response.edit_message(embed=help_main_embed(), view=HelpMainView())


class HelpMainView(SafeView):
    """Menu principal do /help — botoes por categoria. Persistente (Etapa 12):
    custom_id estatico, sem dado sensivel, sobrevive a restart do bot."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        for category in HELP_CATEGORIES:
            self.add_item(_HelpCategoryButton(category))
        self.add_item(_HelpGeneralButton())


class _HelpCategoryButton(discord.ui.Button["HelpMainView"]):
    def __init__(self, category: str) -> None:
        super().__init__(
            label=HELP_CATEGORY_LABELS.get(category, category),
            style=discord.ButtonStyle.primary,
            custom_id=f"limerence:help:category:{category}",
        )
        self.category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        await _open_category(interaction, self.category)


class _HelpGeneralButton(discord.ui.Button["HelpMainView"]):
    def __init__(self) -> None:
        super().__init__(
            label="📚 Geral",
            style=discord.ButtonStyle.secondary,
            custom_id="limerence:help:general",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await _open_general(interaction)


class HelpCategoryView(SafeView):
    """Botao de voltar exibido junto da lista de comandos de uma categoria."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="◀ Menu principal", style=discord.ButtonStyle.secondary, custom_id="limerence:help:back"
    )
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await _back_to_main_menu(interaction)
