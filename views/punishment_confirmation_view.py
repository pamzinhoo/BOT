from __future__ import annotations

import discord
from views.base_view import SafeView


class PunishmentConfirmView(SafeView):
    """Etapa 2: primeira revisao do /punir, antes de qualquer validacao ou escrita no
    banco. Restrita a quem executou o comando."""

    def __init__(self, staff_id: int) -> None:
        super().__init__(timeout=120)
        self.staff_id = staff_id
        self.confirmed: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.staff_id

    @discord.ui.button(label="Verificar e continuar", style=discord.ButtonStyle.primary, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.confirmed = True
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(content="Validando...", view=self)
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.confirmed = False
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(content="Punição cancelada.", view=self)
        self.stop()
