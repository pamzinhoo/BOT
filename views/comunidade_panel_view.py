from __future__ import annotations

from typing import Any

import discord
from views.base_view import SafeView

from utils.constants import EMBED_COLOR_DEFAULT
from views.enquete_panel_view import EnqueteMenuView, enquete_menu_embed
from views.giveaway_panel_view import GiveawayMenuView, giveaway_menu_embed


def comunidade_menu_embed() -> discord.Embed:
    return discord.Embed(
        title="🎉 Comunidade",
        description="Ferramentas de engajamento com a comunidade do servidor.",
        color=EMBED_COLOR_DEFAULT,
    )


class ComunidadeMenuView(SafeView):
    def __init__(self, on_back: Any = None) -> None:
        super().__init__(timeout=300)
        self.on_back = on_back
        if on_back is not None:
            self.add_item(_BackToMainMenuButton(on_back))

    @discord.ui.button(label="🎉 Sorteios", style=discord.ButtonStyle.success)
    async def giveaways_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content=None, embed=giveaway_menu_embed(), view=GiveawayMenuView(on_back=_back_to_comunidade_menu)
        )

    @discord.ui.button(label="🗳️ Enquetes", style=discord.ButtonStyle.primary)
    async def polls_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content=None, embed=enquete_menu_embed(), view=EnqueteMenuView(on_back=_back_to_comunidade_menu)
        )


async def _back_to_comunidade_menu(interaction: discord.Interaction) -> None:
    from views.master_config_view import _back_to_main_menu  # import tardio evita ciclo

    await interaction.response.edit_message(
        content=None, embed=comunidade_menu_embed(), view=ComunidadeMenuView(on_back=_back_to_main_menu)
    )


class _BackToMainMenuButton(discord.ui.Button[Any]):
    def __init__(self, on_back: Any) -> None:
        super().__init__(label="◀ Menu principal", style=discord.ButtonStyle.secondary, row=4)
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.on_back(interaction)
