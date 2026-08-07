from __future__ import annotations

import discord

from utils.checks import member_is_staff
from views.base_view import SafeView


class ConfirmCloseView(SafeView):
    """Confirmacao efemera (Sim/Nao) antes de fechar um ticket de verdade.

    Restrita a quem abriu a confirmacao (closer_id) E que ainda seja staff no
    momento do clique (defesa extra caso o cargo seja removido entre o Fechar
    e o Confirmar)."""

    def __init__(self, closer_id: int) -> None:
        super().__init__(timeout=60)
        self.closer_id = closer_id
        self.confirmed: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.closer_id:
            return False
        return await member_is_staff(interaction)

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.confirmed = True
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(content="Fechando ticket...", view=self)
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.confirmed = False
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(content="Fechamento cancelado.", view=self)
        self.stop()
