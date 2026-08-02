from __future__ import annotations

import discord
from views.base_view import SafeView


class PunishmentExecuteView(SafeView):
    """Etapa 5: segunda confirmacao, mostrada apos a tentativa de DM (Etapa 4) —
    tanto quando a DM foi enviada com sucesso quanto quando falhou. So a punicao
    ainda pendente/notificada e de fato aplicada no Discord aqui."""

    def __init__(self, staff_id: int) -> None:
        super().__init__(timeout=120)
        self.staff_id = staff_id
        self.confirmed: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.staff_id

    @discord.ui.button(label="Aplicar punição", style=discord.ButtonStyle.danger, emoji="🔨")
    async def apply(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.confirmed = True
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(content="Aplicando punição...", view=self)
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.confirmed = False
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(content="Punição cancelada.", view=self)
        self.stop()


class ConfirmView(SafeView):
    """Confirmacao efemera generica (Confirmar/Cancelar), restrita a quem abriu.
    Usada pelo /revogar_punicao."""

    def __init__(self, user_id: int, *, timeout: float = 60) -> None:
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.confirmed: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.confirmed = True
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.confirmed = False
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(view=self)
        self.stop()
