from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import discord

from database.models.log import LogAction
from utils.checks import member_is_staff
from utils.constants import EMBED_COLOR_DANGER, EMBED_COLOR_SUCCESS
from views.base_view import SafeView

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_TIMEOUT_DURATION = timedelta(days=28)  # maximo permitido pelo Discord


async def _report_moderation_error(interaction: discord.Interaction, action: str, exc: discord.HTTPException) -> None:
    if isinstance(exc, discord.Forbidden):
        message = (
            f"Falha ao {action}: sem permissão (403). Verifica em Configurações do Servidor > Cargos "
            "se o cargo do bot tem a permissão necessária (Banir/Expulsar/Moderar Membros) e se esse "
            "cargo está ACIMA do cargo do usuário-alvo na hierarquia — sem isso o Discord recusa a ação."
        )
    else:
        message = f"Falha ao {action}: {exc}"
    await interaction.followup.send(message, ephemeral=True)


async def _deny_if_not_staff(interaction: discord.Interaction) -> bool:
    if await member_is_staff(interaction):
        return False
    await interaction.response.send_message(
        "Apenas a staff pode usar esses botões.", ephemeral=True
    )
    return True


async def _finish(
    interaction: discord.Interaction, view: BlacklistActionView, verdict: str, color: discord.Color
) -> None:
    for item in view.children:
        item.disabled = True  # type: ignore[attr-defined]
    embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None
    if embed is not None:
        embed.color = color
        embed.add_field(name="Resolução", value=verdict, inline=False)
    if interaction.response.is_done():
        if embed is not None:
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.edit_original_response(view=view)
    elif embed is not None:
        await interaction.response.edit_message(embed=embed, view=view)
    else:
        await interaction.response.edit_message(view=view)


class BlacklistActionView(SafeView):
    """Botoes de moderacao anexados ao report de spam no canal de blacklist.
    Nao-persistente — precisa estar vivo no processo do bot pra funcionar,
    igual outros paineis de admin sob demanda deste bot."""

    def __init__(self, target_user_id: int, guild_id: int) -> None:
        super().__init__(timeout=86400)
        self.target_user_id = target_user_id
        self.guild_id = guild_id

    @discord.ui.button(label="Banir", style=discord.ButtonStyle.danger, emoji="🔨")
    async def ban(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if await _deny_if_not_staff(interaction):
            return
        await interaction.response.defer()
        guild = interaction.guild
        assert guild is not None
        try:
            await guild.ban(
                discord.Object(id=self.target_user_id),
                reason=f"Banido por {interaction.user} — spam/blacklist.",
                delete_message_seconds=3600,
            )
        except discord.HTTPException as exc:
            await _report_moderation_error(interaction, "banir", exc)
            return

        await self._log(interaction, f"Usuário <@{self.target_user_id}> banido por {interaction.user.mention}.")
        await _finish(interaction, self, f"🔨 Banido por {interaction.user.mention}.", EMBED_COLOR_DANGER)

    @discord.ui.button(label="Expulsar", style=discord.ButtonStyle.secondary, emoji="👢")
    async def kick(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if await _deny_if_not_staff(interaction):
            return
        await interaction.response.defer()
        guild = interaction.guild
        assert guild is not None
        member = guild.get_member(self.target_user_id)
        if member is None:
            await interaction.followup.send(
                "Usuário não está mais no servidor.", ephemeral=True
            )
            return
        try:
            await member.kick(reason=f"Expulso por {interaction.user} — spam/blacklist.")
        except discord.HTTPException as exc:
            await _report_moderation_error(interaction, "expulsar", exc)
            return

        await self._log(interaction, f"Usuário <@{self.target_user_id}> expulso por {interaction.user.mention}.")
        await _finish(interaction, self, f"👢 Expulso por {interaction.user.mention}.", EMBED_COLOR_DANGER)

    @discord.ui.button(label="Blacklist (28d mute)", style=discord.ButtonStyle.danger, emoji="🚫")
    async def blacklist(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if await _deny_if_not_staff(interaction):
            return
        await interaction.response.defer()
        guild = interaction.guild
        assert guild is not None
        member = guild.get_member(self.target_user_id)
        if member is None:
            await interaction.followup.send(
                "Usuário não está mais no servidor.", ephemeral=True
            )
            return
        try:
            await member.timeout(
                _TIMEOUT_DURATION, reason=f"Blacklist por {interaction.user} — spam."
            )
        except discord.HTTPException as exc:
            await _report_moderation_error(interaction, "aplicar blacklist", exc)
            return

        await self._log(
            interaction,
            f"Usuário <@{self.target_user_id}> colocado em blacklist (mute 28d) por {interaction.user.mention}.",
        )
        await _finish(
            interaction, self, f"🚫 Blacklist (28d) aplicada por {interaction.user.mention}.", EMBED_COLOR_DANGER
        )

    @discord.ui.button(label="Ignorar", style=discord.ButtonStyle.success, emoji="✅")
    async def dismiss(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if await _deny_if_not_staff(interaction):
            return
        await _finish(interaction, self, f"✅ Ignorado por {interaction.user.mention} (falso positivo).", EMBED_COLOR_SUCCESS)

    async def _log(self, interaction: discord.Interaction, message: str) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        await bot.log_service.record(
            guild_id=self.guild_id,
            action=LogAction.BLACKLIST_ACAO,
            actor_discord_id=interaction.user.id,
            message=message,
        )
