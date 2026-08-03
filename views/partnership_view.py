from __future__ import annotations

import discord

from views.base_view import SafeView
from views.embeds import partnership_how_it_works_embed


class PartnershipInfoView(SafeView):
    """Botao fixo na mensagem de boas-vindas do canal de parceiro. Persistente
    (timeout=None + custom_id sem id do usuario) pra sobreviver a restart do
    bot, igual as outras views persistentes do projeto."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Como funciona", emoji="📌", style=discord.ButtonStyle.secondary,
        custom_id="partnership:how_it_works",
    )
    async def how_it_works(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(embed=partnership_how_it_works_embed(), ephemeral=True)
