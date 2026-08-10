from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

import discord

from database.models.audit_log import AuditLogCategory
from services.punishment_service import AppealError
from utils.checks import member_can, member_is_owner_or_ceo
from views.base_view import SafeView
from views.embeds import (
    appeal_accepted_dm_embed,
    appeal_denied_dm_embed,
    appeal_review_embed,
    punishment_revoked_log_embed,
)

if TYPE_CHECKING:
    from core.bot import LimerenceBot


async def send_appeal_to_review_channel(
    bot: LimerenceBot, appeal, *, executor_name: str | None = None
) -> None:
    """Posta o embed de recurso no canal de recursos da guild e registra a auditoria
    (Etapa 17/DM fallback). Compartilhado entre AppealModal, /recorrer e o fallback por DM."""
    punishment = await bot.punishment_service.get_by_id(appeal.punishment_id)
    if punishment is None:
        return

    await bot.audit_log_service.record(
        guild_id=punishment.guild_id,
        category=AuditLogCategory.PUNISHMENT_APPEAL,
        action="PUNISHMENT_APPEAL_CREATED",
        executor_id=appeal.user_id,
        executor_name=executor_name or str(appeal.user_id),
        target_id=punishment.user_id,
        target_name=punishment.user_name,
        reason=None,
        details={"punishment_code": punishment.punishment_code, "method": appeal.method.value},
    )

    guild = bot.get_guild(punishment.guild_id)
    if guild is None:
        return
    settings = await bot.config_service.get_settings(guild.id)
    if settings.appeal_channel_id is None:
        return
    channel = guild.get_channel(settings.appeal_channel_id)
    if not isinstance(channel, discord.TextChannel):
        return

    message = await channel.send(
        embed=appeal_review_embed(punishment, appeal),
        view=appeal_review_view(appeal.id),
    )
    await bot.punishment_service.set_appeal_channel_message(appeal.id, message.id)


async def _resolve_review_message(
    interaction: discord.Interaction, appeal
) -> discord.Message | None:
    """Modais abertos a partir de um botao nem sempre trazem `interaction.message`
    preenchido — cai pro fetch via ID salvo no recurso (Etapa 17)."""
    if isinstance(interaction.message, discord.Message):
        return interaction.message
    if interaction.channel is not None and appeal.channel_message_id is not None:
        try:
            return await interaction.channel.fetch_message(appeal.channel_message_id)  # type: ignore[union-attr]
        except discord.HTTPException:
            return None
    return None


class AppealModal(discord.ui.Modal, title="Recurso de punição"):
    """Etapa 16: aberto ao clicar em 'Recorrer da punição' na DM."""

    motivo = discord.ui.TextInput(
        label="Motivo do recurso",
        placeholder="Explique por que sua punição deveria ser removida.",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True,
    )
    informacoes_adicionais = discord.ui.TextInput(
        label="Informações adicionais",
        placeholder="Digite qualquer informação que possa ajudar na análise.",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False,
    )

    def __init__(self, punishment_id: uuid.UUID) -> None:
        super().__init__()
        self.punishment_id = punishment_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        # Deferir de imediato: submit_appeal e um write no banco antes de termos
        # algo pra responder, o que facilmente passa dos 3s de prazo.
        await interaction.response.defer()
        try:
            appeal = await bot.punishment_service.submit_appeal(
                punishment_id=self.punishment_id,
                user_id=interaction.user.id,
                message=str(self.motivo),
                additional_info=str(self.informacoes_adicionais) or None,
            )
        except AppealError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        await interaction.followup.send(
            "Recurso enviado! A staff vai analisar e você será notificado por aqui.", ephemeral=True
        )

        await send_appeal_to_review_channel(bot, appeal, executor_name=str(interaction.user))


class DenyAppealModal(discord.ui.Modal, title="Negar recurso"):
    """Etapa 19: aberto ao clicar em 'Negar recurso' no canal de recursos."""

    motivo = discord.ui.TextInput(
        label="Motivo da negativa",
        placeholder="Explique por que o recurso foi recusado.",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True,
    )

    def __init__(self, appeal_id: uuid.UUID) -> None:
        super().__init__()
        self.appeal_id = appeal_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        member = interaction.user
        if not isinstance(member, discord.Member) or interaction.guild is None:
            return
        guild = interaction.guild

        # Deferir de imediato: deny_appeal e um write no banco seguido de
        # edicao de mensagem e DM — tudo isso facilmente passa dos 3s de prazo.
        await interaction.response.defer()
        settings = await bot.config_service.get_settings(guild.id)
        try:
            result = await bot.punishment_service.deny_appeal(
                guild=guild,
                appeal_id=self.appeal_id,
                reviewer=member,
                reason=str(self.motivo),
                review_role_id=settings.review_role_id,
                bypass_self_review=await member_is_owner_or_ceo(interaction),
            )
        except AppealError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        message = await _resolve_review_message(interaction, result.appeal)
        if message is not None:
            try:
                await message.edit(embed=appeal_review_embed(result.punishment, result.appeal), view=None)
            except discord.HTTPException:
                pass

        user = guild.get_member(result.punishment.user_id) or bot.get_user(result.punishment.user_id)
        if user is not None:
            try:
                await user.send(embed=appeal_denied_dm_embed(str(self.motivo), str(member)))
            except discord.HTTPException:
                pass

        await interaction.followup.send("Recurso negado.", ephemeral=True)


class AppealButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"limerence:appeal:open:(?P<punishment_id>[0-9a-fA-F-]{36})",
):
    """Botao persistente na DM do punido (Etapa 15). Sobrevive a restart do bot."""

    def __init__(self, punishment_id: uuid.UUID) -> None:
        super().__init__(
            discord.ui.Button(
                label="Recorrer da punição",
                style=discord.ButtonStyle.primary,
                emoji="📨",
                custom_id=f"limerence:appeal:open:{punishment_id}",
            )
        )
        self.punishment_id = punishment_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]
    ) -> AppealButton:
        return cls(uuid.UUID(match["punishment_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(AppealModal(self.punishment_id))


class AppealAcceptButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"limerence:appeal:accept:(?P<appeal_id>[0-9a-fA-F-]{36})",
):
    """Botao persistente no canal de recursos (Etapa 18)."""

    def __init__(self, appeal_id: uuid.UUID) -> None:
        super().__init__(
            discord.ui.Button(
                label="Aceitar recurso",
                style=discord.ButtonStyle.success,
                emoji="✅",
                custom_id=f"limerence:appeal:accept:{appeal_id}",
            )
        )
        self.appeal_id = appeal_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]
    ) -> AppealAcceptButton:
        return cls(uuid.UUID(match["appeal_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        if not await member_can(interaction, "recurso_banimento"):
            await interaction.response.send_message(
                "Apenas a staff pode usar esse botão.", ephemeral=True
            )
            return
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)
        settings = await bot.config_service.get_settings(guild.id)
        try:
            result = await bot.punishment_service.accept_appeal(
                guild=guild,
                appeal_id=self.appeal_id,
                reviewer=member,
                review_role_id=settings.review_role_id,
                bypass_self_review=await member_is_owner_or_ceo(interaction),
            )
        except AppealError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        if isinstance(interaction.message, discord.Message):
            try:
                await interaction.message.edit(
                    embed=appeal_review_embed(result.punishment, result.appeal), view=None
                )
            except discord.HTTPException:
                pass

        settings = await bot.config_service.get_settings(guild.id)
        if settings.log_punishments_channel_id is not None:
            log_channel = guild.get_channel(settings.log_punishments_channel_id)
            if isinstance(log_channel, discord.abc.Messageable):
                await log_channel.send(
                    embed=punishment_revoked_log_embed(result.punishment, via_appeal=True)
                )

        user = guild.get_member(result.punishment.user_id) or bot.get_user(result.punishment.user_id)
        if user is not None:
            try:
                await user.send(embed=appeal_accepted_dm_embed(result.punishment, str(member)))
            except discord.HTTPException:
                pass

        await interaction.followup.send("Recurso aceito. Punição revogada.", ephemeral=True)


class AppealDenyButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"limerence:appeal:deny:(?P<appeal_id>[0-9a-fA-F-]{36})",
):
    """Botao persistente no canal de recursos (Etapa 19)."""

    def __init__(self, appeal_id: uuid.UUID) -> None:
        super().__init__(
            discord.ui.Button(
                label="Negar recurso",
                style=discord.ButtonStyle.danger,
                emoji="❌",
                custom_id=f"limerence:appeal:deny:{appeal_id}",
            )
        )
        self.appeal_id = appeal_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]
    ) -> AppealDenyButton:
        return cls(uuid.UUID(match["appeal_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await member_can(interaction, "recurso_banimento"):
            await interaction.response.send_message(
                "Apenas a staff pode usar esse botão.", ephemeral=True
            )
            return
        await interaction.response.send_modal(DenyAppealModal(self.appeal_id))


def punishment_dm_view(punishment_id: uuid.UUID) -> discord.ui.View:
    """View com o botao de recurso, enviada junto do embed de aviso de punicao na DM
    (Etapa 4/15) — antes e depois da punicao ser de fato aplicada."""
    view = SafeView(timeout=None)
    view.add_item(AppealButton(punishment_id))
    return view


def appeal_review_view(appeal_id: uuid.UUID) -> discord.ui.View:
    view = SafeView(timeout=None)
    view.add_item(AppealAcceptButton(appeal_id))
    view.add_item(AppealDenyButton(appeal_id))
    return view
