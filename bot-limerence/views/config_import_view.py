from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from database.models.audit_log import AuditLogCategory
from services.config_transfer_service import ImportFieldChange, apply_import_plan

if TYPE_CHECKING:
    from core.bot import LimerenceBot


class ConfigImportConfirmView(discord.ui.View):
    """Confirmacao antes de aplicar um /config import. So quem pediu a importacao
    pode confirmar/cancelar. Nao-persistente — expira em 3 minutos."""

    def __init__(
        self,
        guild_id: int,
        plan: dict[str, dict[str, object]],
        changes: list[ImportFieldChange],
        requester_id: int,
        source_filename: str,
        source_data: dict,
        integrity: str,
    ) -> None:
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.plan = plan
        self.changes = changes
        self.requester_id = requester_id
        self.source_filename = source_filename
        self.source_data = source_data
        self.integrity = integrity

    async def _deny_if_not_requester(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return False
        await interaction.response.send_message(
            "Só quem pediu a importação pode confirmar ou cancelar.", ephemeral=True
        )
        return True

    @discord.ui.button(label="Confirmar importação", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if await self._deny_if_not_requester(interaction):
            return
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]

        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(view=self)

        await apply_import_plan(bot, self.guild_id, self.plan)

        unresolved_count = sum(1 for c in self.changes if c.included and c.status == "unresolved")
        changed_count = sum(1 for c in self.changes if c.changed and c.status != "unresolved")
        await bot.audit_log_service.record(
            guild_id=self.guild_id,
            category=AuditLogCategory.SERVER_CONFIG,
            action="Configurações importadas",
            executor_id=self.requester_id,
            details={
                "arquivo": self.source_filename,
                "origem_servidor": self.source_data.get("guild_name"),
                "origem_exportado_em": self.source_data.get("exported_at"),
                "config_version": self.source_data.get("config_version"),
                "integridade": self.integrity,
                "campos_alterados": changed_count,
                "campos_nao_resolvidos": unresolved_count,
            },
        )

        await interaction.followup.send(
            f"✅ Configuração importada — {changed_count} campo(s) alterado(s)"
            + (f", {unresolved_count} não resolvido(s)." if unresolved_count else "."),
            ephemeral=True,
        )
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if await self._deny_if_not_requester(interaction):
            return
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(content="Importação cancelada.", embed=None, view=self)
        self.stop()
