from __future__ import annotations

import discord

from core.logger import get_logger

logger = get_logger("views")


class SafeView(discord.ui.View):
    """Base pra todas as Views de botao/select do bot. Sem isso, qualquer excecao
    dentro de um callback (ex.: erro de banco) morre silenciosa no discord.py —
    a interacao nunca e respondida e o Discord mostra 'app nao respondeu a tempo'.
    Aqui a excecao e logada e o usuario recebe uma mensagem de erro de verdade."""

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item
    ) -> None:
        logger.exception(
            "Erro nao tratado num componente (%s) na guild %s.",
            type(item).__name__, interaction.guild_id, exc_info=error,
        )
        message = "❌ Ocorreu um erro ao processar essa ação. Já foi registrado nos logs."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass
