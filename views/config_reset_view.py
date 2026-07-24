from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from database.models.audit_log import AuditLogCategory
from services.config_reset_service import reset_all_guild_config

if TYPE_CHECKING:
    from core.bot import LimerenceBot


def reset_all_warning_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚠️ Restaurar TODAS as configurações",
        description=(
            "Isso vai restaurar **todas as categorias** de configuração deste servidor "
            "para os valores padrão (Tickets, Cargos, Permissões, Dashboard, Ranking, "
            "Avaliações, Anti-Spam, Auditoria, Alertas).\n\n"
            "**Esta ação não pode ser desfeita.**\n\n"
            "Tickets, estatísticas, ranking, histórico, transcrições e avaliações "
            "recebidas **não** são apagados — só as configurações."
        ),
    )
    return embed


class ConfigResetAllConfirmView(discord.ui.View):
    """Confirmação do reset geral. So quem pediu pode confirmar/cancelar —
    igual ConfigImportConfirmView. Nao-persistente — expira em 2 minutos."""

    def __init__(self, requester_id: int) -> None:
        super().__init__(timeout=120)
        self.requester_id = requester_id

    async def _deny_if_not_requester(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return False
        await interaction.response.send_message(
            "Só quem pediu o reset geral pode confirmar ou cancelar.", ephemeral=True
        )
        return True

    @discord.ui.button(label="Confirmar reset geral", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if await self._deny_if_not_requester(interaction):
            return
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]

        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(view=self)

        changed = await reset_all_guild_config(bot, interaction.guild_id)
        total = sum(changed.values())

        await bot.audit_log_service.record(
            guild_id=interaction.guild_id,
            category=AuditLogCategory.SERVER_CONFIG,
            action="Reset geral executado",
            executor_id=interaction.user.id,
            executor_name=str(interaction.user),
            config_category="Sistema",
            config_name="Reset Geral",
            old_value=f"{total} configuração(ões) personalizada(s)",
            new_value="Todas restauradas para o padrão",
        )

        lines = "\n".join(f"{title}: {count} campo(s)" for title, count in changed.items())
        await interaction.followup.send(
            f"✅ Reset geral concluído — {total} campo(s) alterado(s) no total.\n\n{lines}",
            ephemeral=True,
        )
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if await self._deny_if_not_requester(interaction):
            return
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(content="Reset geral cancelado.", embed=None, view=self)
        self.stop()
