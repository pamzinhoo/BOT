from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord
from views.base_view import SafeView

from database.models.punishment import PunishmentStatus
from services.punishment_review_service import (
    PendingPunishmentItem,
    PunishmentReviewError,
    PunishmentReviewService,
)
from utils.checks import member_can
from utils.time import humanize_duration
from views.embeds import pending_punishment_detail_embed, pending_punishments_embed

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_DENIAL_MESSAGE = "❌ Você não possui permissão para visualizar punições em análise."
_STATE_PATTERN = (
    r"(?P<guild_id>\d+):(?P<filtro>[a-z]+):(?P<staff_id>\d+):(?P<page>\d+)"
)


def _time_remaining_label(punishment) -> str:
    if punishment.status != PunishmentStatus.PENDING_REVIEW or punishment.review_deadline_at is None:
        return "—"
    remaining_seconds = (punishment.review_deadline_at - datetime.now(UTC)).total_seconds()
    if remaining_seconds <= 0:
        return "Expirado"
    return humanize_duration(int(remaining_seconds))


async def _find_role_divergence(
    bot: "LimerenceBot", guild_id: int
) -> list[discord.Member]:
    """Membros com o cargo 'Em Análise' no Discord sem punição PENDING_REVIEW no banco.
    Só um alerta visual pro /analises — nunca usado como fonte pra listar punições."""
    guild = bot.get_guild(guild_id)
    if guild is None:
        return []
    settings = await bot.config_service.get_settings(guild_id)
    if settings.review_role_id is None:
        return []
    role = guild.get_role(settings.review_role_id)
    if role is None or not role.members:
        return []

    all_pending = await bot.punishment_review_service.list_pending(guild_id, filtro="todos", staff_id=None)
    covered_ids = {item.punishment.user_id for item in all_pending}
    role_ids = {member.id for member in role.members}
    divergent_ids = PunishmentReviewService.divergent_user_ids(role_ids, covered_ids)
    return [member for member in role.members if member.id in divergent_ids]


async def build_panel(
    bot: "LimerenceBot", *, guild_id: int, filtro: str, staff_id: int, page: int
) -> tuple[discord.Embed, discord.ui.View]:
    items = await bot.punishment_review_service.list_pending(
        guild_id, filtro=filtro, staff_id=staff_id or None
    )
    page_items, total_pages = PunishmentReviewService.paginate(items, page)
    page = min(max(page, 1), total_pages)
    divergent_members = await _find_role_divergence(bot, guild_id)
    embed = pending_punishments_embed(
        page_items,
        total_count=len(items),
        page=page,
        total_pages=total_pages,
        divergent_members=divergent_members,
    )
    view = pending_punishments_view(
        guild_id=guild_id, filtro=filtro, staff_id=staff_id, page=page, total_pages=total_pages,
        page_items=page_items,
    )
    return embed, view


def _select_options(page_items: list[PendingPunishmentItem]) -> list[discord.SelectOption]:
    if not page_items:
        return [discord.SelectOption(label="Nenhuma punição nesta página", value="none", default=True)]
    return [
        discord.SelectOption(
            label=f"{item.punishment.punishment_code} — {item.punishment.user_name or item.punishment.user_id}"[:100],
            value=str(item.punishment.id),
            description=PunishmentStatus.PENDING_REVIEW.value,
        )
        for item in page_items
    ]


class AnalisesNavButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=rf"limerence:analises:nav:{_STATE_PATTERN}:(?P<action>prev|next|refresh)",
):
    """Botões Anterior/Próxima/Atualizar do painel /analises. Persistente (DynamicItem)."""

    _LABELS = {"prev": ("⬅️ Anterior", discord.ButtonStyle.secondary), "next": ("➡️ Próxima", discord.ButtonStyle.secondary), "refresh": ("🔄 Atualizar", discord.ButtonStyle.primary)}

    def __init__(
        self, *, guild_id: int, filtro: str, staff_id: int, page: int, action: str, disabled: bool = False
    ) -> None:
        label, style = self._LABELS[action]
        super().__init__(
            discord.ui.Button(
                label=label,
                style=style,
                disabled=disabled,
                custom_id=f"limerence:analises:nav:{guild_id}:{filtro}:{staff_id}:{page}:{action}",
            )
        )
        self.guild_id = guild_id
        self.filtro = filtro
        self.staff_id = staff_id
        self.page = page
        self.action = action

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]
    ) -> "AnalisesNavButton":
        return cls(
            guild_id=int(match["guild_id"]),
            filtro=match["filtro"],
            staff_id=int(match["staff_id"]),
            page=int(match["page"]),
            action=match["action"],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await member_can(interaction, "analises"):
            await interaction.response.send_message(_DENIAL_MESSAGE, ephemeral=True)
            return
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]

        if self.action == "prev":
            target_page = self.page - 1
        elif self.action == "next":
            target_page = self.page + 1
        else:
            target_page = self.page

        embed, view = await build_panel(
            bot, guild_id=self.guild_id, filtro=self.filtro, staff_id=self.staff_id, page=target_page
        )
        await interaction.response.edit_message(embed=embed, view=view)


class AnalisesSelect(
    discord.ui.DynamicItem[discord.ui.Select],
    template=rf"limerence:analises:select:{_STATE_PATTERN}",
):
    """Menu pra escolher uma punição da página atual e ver o detalhe completo."""

    def __init__(
        self,
        *,
        guild_id: int,
        filtro: str,
        staff_id: int,
        page: int,
        options: list[discord.SelectOption],
    ) -> None:
        super().__init__(
            discord.ui.Select(
                placeholder="Selecione uma punição pra ver detalhes...",
                options=options,
                custom_id=f"limerence:analises:select:{guild_id}:{filtro}:{staff_id}:{page}",
            )
        )
        self.guild_id = guild_id
        self.filtro = filtro
        self.staff_id = staff_id
        self.page = page

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]
    ) -> "AnalisesSelect":
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        guild_id = int(match["guild_id"])
        filtro = match["filtro"]
        staff_id = int(match["staff_id"])
        page = int(match["page"])
        items = await bot.punishment_review_service.list_pending(
            guild_id, filtro=filtro, staff_id=staff_id or None
        )
        page_items, total_pages = PunishmentReviewService.paginate(items, page)
        page = min(max(page, 1), total_pages)
        return cls(guild_id=guild_id, filtro=filtro, staff_id=staff_id, page=page, options=_select_options(page_items))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await member_can(interaction, "analises"):
            await interaction.response.send_message(_DENIAL_MESSAGE, ephemeral=True)
            return
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        value = self.item.values[0]
        if value == "none":
            await interaction.response.defer()
            return

        review_item = await bot.punishment_review_service.get_item(uuid.UUID(value))
        if review_item is None:
            await interaction.response.send_message("Punição não encontrada.", ephemeral=True)
            return

        embed = pending_punishment_detail_embed(
            review_item, time_remaining=_time_remaining_label(review_item.punishment)
        )
        view = pending_punishment_detail_view(
            punishment_id=review_item.punishment.id,
            guild_id=self.guild_id,
            filtro=self.filtro,
            staff_id=self.staff_id,
            page=self.page,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class AnalisesBackButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=rf"limerence:analises:back:{_STATE_PATTERN}",
):
    """Volta da tela de detalhe pra lista paginada."""

    def __init__(self, *, guild_id: int, filtro: str, staff_id: int, page: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="⬅️ Voltar à lista",
                style=discord.ButtonStyle.secondary,
                custom_id=f"limerence:analises:back:{guild_id}:{filtro}:{staff_id}:{page}",
            )
        )
        self.guild_id = guild_id
        self.filtro = filtro
        self.staff_id = staff_id
        self.page = page

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]
    ) -> "AnalisesBackButton":
        return cls(
            guild_id=int(match["guild_id"]),
            filtro=match["filtro"],
            staff_id=int(match["staff_id"]),
            page=int(match["page"]),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await member_can(interaction, "analises"):
            await interaction.response.send_message(_DENIAL_MESSAGE, ephemeral=True)
            return
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        embed, view = await build_panel(
            bot, guild_id=self.guild_id, filtro=self.filtro, staff_id=self.staff_id, page=self.page
        )
        await interaction.response.edit_message(embed=embed, view=view)


class AnalisesAcceptButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"limerence:analises:accept:(?P<punishment_id>[0-9a-fA-F-]{36})",
):
    def __init__(self, punishment_id: uuid.UUID) -> None:
        super().__init__(
            discord.ui.Button(
                label="Aceitar recurso",
                style=discord.ButtonStyle.success,
                emoji="✅",
                custom_id=f"limerence:analises:accept:{punishment_id}",
            )
        )
        self.punishment_id = punishment_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]
    ) -> "AnalisesAcceptButton":
        return cls(uuid.UUID(match["punishment_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await member_can(interaction, "analises"):
            await interaction.response.send_message(_DENIAL_MESSAGE, ephemeral=True)
            return
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]

        await interaction.response.defer(ephemeral=True)
        settings = await bot.config_service.get_settings(guild.id)
        try:
            result = await bot.punishment_review_service.accept(
                guild=guild,
                punishment_id=self.punishment_id,
                reviewer=member,
                review_role_id=settings.review_role_id,
            )
        except PunishmentReviewError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        from views.embeds import appeal_accepted_dm_embed, punishment_revoked_log_embed

        if isinstance(interaction.message, discord.Message):
            try:
                await interaction.message.edit(
                    embed=discord.Embed(
                        title="✅ Recurso aceito pelo painel /analises",
                        description=f"Punição `{result.punishment.punishment_code}` revogada.",
                        color=discord.Color.green(),
                    ),
                    view=None,
                )
            except discord.HTTPException:
                pass

        if settings.log_punishments_channel_id is not None:
            log_channel = guild.get_channel(settings.log_punishments_channel_id)
            if isinstance(log_channel, discord.abc.Messageable):
                await log_channel.send(embed=punishment_revoked_log_embed(result.punishment, via_appeal=True))

        user = guild.get_member(result.punishment.user_id) or bot.get_user(result.punishment.user_id)
        if user is not None:
            try:
                await user.send(embed=appeal_accepted_dm_embed(result.punishment, str(member)))
            except discord.HTTPException:
                pass

        await interaction.followup.send("Recurso aceito. Punição revogada.", ephemeral=True)


class AnalisesDenyModal(discord.ui.Modal, title="Negar recurso"):
    motivo = discord.ui.TextInput(
        label="Motivo da negativa",
        placeholder="Explique por que o recurso foi recusado.",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True,
    )

    def __init__(self, punishment_id: uuid.UUID) -> None:
        super().__init__()
        self.punishment_id = punishment_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]

        settings = await bot.config_service.get_settings(guild.id)
        try:
            result = await bot.punishment_review_service.deny(
                guild=guild,
                punishment_id=self.punishment_id,
                reviewer=member,
                reason=str(self.motivo),
                review_role_id=settings.review_role_id,
            )
        except PunishmentReviewError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        from views.embeds import appeal_denied_dm_embed, punishment_log_embed

        if isinstance(interaction.message, discord.Message):
            try:
                await interaction.message.edit(
                    embed=discord.Embed(
                        title="❌ Recurso negado pelo painel /analises",
                        description=f"Punição `{result.punishment.punishment_code}` aplicada.",
                        color=discord.Color.red(),
                    ),
                    view=None,
                )
            except discord.HTTPException:
                pass

        if settings.log_punishments_channel_id is not None:
            log_channel = guild.get_channel(settings.log_punishments_channel_id)
            if isinstance(log_channel, discord.abc.Messageable):
                await log_channel.send(embed=punishment_log_embed(result.punishment))

        user = guild.get_member(result.punishment.user_id) or bot.get_user(result.punishment.user_id)
        if user is not None:
            try:
                await user.send(embed=appeal_denied_dm_embed(str(self.motivo), str(member)))
            except discord.HTTPException:
                pass

        await interaction.response.send_message("Recurso negado.", ephemeral=True)


class AnalisesDenyButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"limerence:analises:deny:(?P<punishment_id>[0-9a-fA-F-]{36})",
):
    def __init__(self, punishment_id: uuid.UUID) -> None:
        super().__init__(
            discord.ui.Button(
                label="Negar recurso",
                style=discord.ButtonStyle.danger,
                emoji="❌",
                custom_id=f"limerence:analises:deny:{punishment_id}",
            )
        )
        self.punishment_id = punishment_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]
    ) -> "AnalisesDenyButton":
        return cls(uuid.UUID(match["punishment_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await member_can(interaction, "analises"):
            await interaction.response.send_message(_DENIAL_MESSAGE, ephemeral=True)
            return
        await interaction.response.send_modal(AnalisesDenyModal(self.punishment_id))


def pending_punishments_view(
    *,
    guild_id: int,
    filtro: str,
    staff_id: int,
    page: int,
    total_pages: int,
    page_items: list[PendingPunishmentItem],
) -> discord.ui.View:
    view = SafeView(timeout=None)
    view.add_item(
        AnalisesSelect(
            guild_id=guild_id, filtro=filtro, staff_id=staff_id, page=page, options=_select_options(page_items)
        )
    )
    view.add_item(
        AnalisesNavButton(
            guild_id=guild_id, filtro=filtro, staff_id=staff_id, page=page, action="prev", disabled=page <= 1
        )
    )
    view.add_item(
        AnalisesNavButton(
            guild_id=guild_id, filtro=filtro, staff_id=staff_id, page=page, action="next",
            disabled=page >= total_pages,
        )
    )
    view.add_item(
        AnalisesNavButton(guild_id=guild_id, filtro=filtro, staff_id=staff_id, page=page, action="refresh")
    )
    return view


def pending_punishment_detail_view(
    *, punishment_id: uuid.UUID, guild_id: int, filtro: str, staff_id: int, page: int
) -> discord.ui.View:
    view = SafeView(timeout=None)
    view.add_item(AnalisesAcceptButton(punishment_id))
    view.add_item(AnalisesDenyButton(punishment_id))
    view.add_item(AnalisesBackButton(guild_id=guild_id, filtro=filtro, staff_id=staff_id, page=page))
    return view
