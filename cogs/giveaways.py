from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import discord
from discord.ext import commands, tasks
from views.base_view import SafeView

from core.bot import LimerenceBot
from core.logger import get_logger
from database.models.audit_log import AuditLogCategory
from database.models.giveaway import Giveaway
from services.giveaway_service import AlreadyEnteredError, NotEnteredError
from utils.checks import member_is_staff
from utils.debounce import try_acquire
from views.embeds import giveaway_panel_embed, giveaway_result_embed

logger = get_logger("giveaways")

_CHECK_INTERVAL_MINUTES = 1


class GiveawayEnterButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"giveaway:enter:(?P<giveaway_id>[0-9a-fA-F-]{36})",
):
    def __init__(self, giveaway_id: uuid.UUID) -> None:
        super().__init__(
            discord.ui.Button(
                label="🎉 Participar",
                style=discord.ButtonStyle.success,
                custom_id=f"giveaway:enter:{giveaway_id}",
            )
        )
        self.giveaway_id = giveaway_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: Any
    ) -> "GiveawayEnterButton":
        return cls(uuid.UUID(match["giveaway_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member):
            return

        # Trava contra duplo-clique/spam no botao: enquanto o 1o clique deste
        # usuario neste sorteio ainda esta em voo, cliques extras nem tocam
        # banco nem editam a mensagem de novo.
        with try_acquire(("giveaway:enter", self.giveaway_id, member.id)) as acquired:
            if not acquired:
                await interaction.response.send_message(
                    "⏳ Seu clique anterior ainda está sendo processado, aguarde.", ephemeral=True
                )
                return

            bot: LimerenceBot = interaction.client  # type: ignore[assignment]

            # Defere de imediato: get_giveaway/can_enter/enter sao chamadas ao
            # banco que podem passar dos 3s de prazo do Discord antes da 1a
            # resposta, num botao publico de participacao.
            await interaction.response.defer()

            giveaway = await bot.giveaway_service.get_giveaway(self.giveaway_id)
            if giveaway is None or giveaway.guild_id != interaction.guild_id:
                await interaction.followup.send("Sorteio não encontrado.", ephemeral=True)
                return

            can_enter, reason = await bot.giveaway_service.can_enter(giveaway, member)
            if not can_enter:
                await interaction.followup.send(
                    reason or "Você não pode participar desse sorteio.", ephemeral=True
                )
                return

            try:
                await bot.giveaway_service.enter(giveaway, member)
            except AlreadyEnteredError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return

            await interaction.followup.send("✅ Você está participando do sorteio!", ephemeral=True)

            count = await bot.giveaway_service.count_entries(giveaway.id)
            if interaction.message is not None:
                try:
                    await interaction.message.edit(embed=giveaway_panel_embed(giveaway, count))
                except discord.HTTPException:
                    logger.warning(
                        "Falha ao atualizar contagem de participantes do sorteio %s.", giveaway.id
                    )


class GiveawayLeaveButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"giveaway:leave:(?P<giveaway_id>[0-9a-fA-F-]{36})",
):
    def __init__(self, giveaway_id: uuid.UUID) -> None:
        super().__init__(
            discord.ui.Button(
                label="🚪 Sair do sorteio",
                style=discord.ButtonStyle.secondary,
                custom_id=f"giveaway:leave:{giveaway_id}",
            )
        )
        self.giveaway_id = giveaway_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: Any
    ) -> "GiveawayLeaveButton":
        return cls(uuid.UUID(match["giveaway_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member):
            return

        with try_acquire(("giveaway:leave", self.giveaway_id, member.id)) as acquired:
            if not acquired:
                await interaction.response.send_message(
                    "⏳ Seu clique anterior ainda está sendo processado, aguarde.", ephemeral=True
                )
                return

            bot: LimerenceBot = interaction.client  # type: ignore[assignment]
            await interaction.response.defer()

            giveaway = await bot.giveaway_service.get_giveaway(self.giveaway_id)
            if giveaway is None or giveaway.guild_id != interaction.guild_id:
                await interaction.followup.send("Sorteio não encontrado.", ephemeral=True)
                return

            try:
                await bot.giveaway_service.leave(giveaway, member)
            except NotEnteredError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return

            await interaction.followup.send("👋 Você saiu do sorteio.", ephemeral=True)

            count = await bot.giveaway_service.count_entries(giveaway.id)
            if interaction.message is not None:
                try:
                    await interaction.message.edit(embed=giveaway_panel_embed(giveaway, count))
                except discord.HTTPException:
                    logger.warning(
                        "Falha ao atualizar contagem de participantes do sorteio %s.", giveaway.id
                    )


class GiveawayCloseButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"giveaway:close:(?P<giveaway_id>[0-9a-fA-F-]{36})",
):
    def __init__(self, giveaway_id: uuid.UUID) -> None:
        super().__init__(
            discord.ui.Button(
                label="🔒 Encerrar Sorteio",
                style=discord.ButtonStyle.danger,
                custom_id=f"giveaway:close:{giveaway_id}",
            )
        )
        self.giveaway_id = giveaway_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: Any
    ) -> "GiveawayCloseButton":
        return cls(uuid.UUID(match["giveaway_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await member_is_staff(interaction):
            await interaction.response.send_message(
                "Só a staff pode encerrar um sorteio.", ephemeral=True
            )
            return
        with try_acquire(("giveaway:close", self.giveaway_id)) as acquired:
            if not acquired:
                await interaction.response.send_message(
                    "⏳ Esse sorteio já está sendo encerrado.", ephemeral=True
                )
                return
            bot: LimerenceBot = interaction.client  # type: ignore[assignment]
            await interaction.response.defer()
            await close_and_announce(bot, self.giveaway_id)


class GiveawayRerollButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"giveaway:reroll:(?P<giveaway_id>[0-9a-fA-F-]{36})",
):
    def __init__(self, giveaway_id: uuid.UUID) -> None:
        super().__init__(
            discord.ui.Button(
                label="🔁 Sortear novamente",
                style=discord.ButtonStyle.secondary,
                custom_id=f"giveaway:reroll:{giveaway_id}",
            )
        )
        self.giveaway_id = giveaway_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: Any
    ) -> "GiveawayRerollButton":
        return cls(uuid.UUID(match["giveaway_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await member_is_staff(interaction):
            await interaction.response.send_message(
                "Só a staff pode sortear novamente.", ephemeral=True
            )
            return
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        await interaction.response.defer()
        result = await bot.giveaway_service.reroll(self.giveaway_id)
        if result is None:
            return
        giveaway, winners = result
        await _announce_winners(bot, giveaway, winners, is_reroll=True)
        await bot.audit_log_service.record(
            guild_id=giveaway.guild_id,
            category=AuditLogCategory.GIVEAWAY,
            action="SORTEIO_REALIZADO_NOVAMENTE",
            executor_id=interaction.user.id,
            executor_name=str(interaction.user),
            details={"giveaway_id": str(giveaway.id), "title": giveaway.title, "winners": winners},
        )


class GiveawayOpenView(SafeView):
    def __init__(self, giveaway_id: uuid.UUID) -> None:
        super().__init__(timeout=None)
        self.add_item(GiveawayEnterButton(giveaway_id))
        self.add_item(GiveawayLeaveButton(giveaway_id))
        self.add_item(GiveawayCloseButton(giveaway_id))


class GiveawayClosedView(SafeView):
    def __init__(self, giveaway_id: uuid.UUID) -> None:
        super().__init__(timeout=None)
        self.add_item(GiveawayRerollButton(giveaway_id))


async def _announce_winners(
    bot: LimerenceBot, giveaway: Giveaway, winners: list[int], *, is_reroll: bool
) -> None:
    guild = bot.get_guild(giveaway.guild_id)
    if guild is None:
        return
    channel = guild.get_channel(giveaway.channel_id)
    if giveaway.message_id is not None and isinstance(channel, discord.abc.Messageable):
        try:
            message = await channel.fetch_message(giveaway.message_id)
            await message.edit(view=GiveawayClosedView(giveaway.id))
        except discord.HTTPException:
            pass
    if isinstance(channel, discord.abc.Messageable):
        try:
            await channel.send(embed=giveaway_result_embed(giveaway, winners, is_reroll=is_reroll))
        except discord.HTTPException:
            logger.exception("Falha ao enviar resultado do sorteio %s.", giveaway.id)


async def close_and_announce(bot: LimerenceBot, giveaway_id: uuid.UUID) -> None:
    result = await bot.giveaway_service.close_and_draw(giveaway_id)
    if result is None:
        return
    giveaway, winners = result
    await _announce_winners(bot, giveaway, winners, is_reroll=False)
    await bot.audit_log_service.record(
        guild_id=giveaway.guild_id,
        category=AuditLogCategory.GIVEAWAY,
        action="SORTEIO_ENCERRADO",
        details={"giveaway_id": str(giveaway.id), "title": giveaway.title, "winners": winners},
    )


class GiveawaysCog(commands.Cog):
    """Sistema de Sorteios. Toda regra de negocio vive em GiveawayService —
    esta Cog so mantem os botoes persistentes e a varredura de encerramento
    automatico, seguindo o mesmo padrao de PollsCog."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self.close_expired_giveaways.start()

    def cog_unload(self) -> None:
        self.close_expired_giveaways.cancel()

    @tasks.loop(minutes=_CHECK_INTERVAL_MINUTES)
    async def close_expired_giveaways(self) -> None:
        now = datetime.now(UTC)
        for giveaway in await self.bot.giveaway_service.list_open_expiring(now):
            try:
                await close_and_announce(self.bot, giveaway.id)
            except Exception:
                logger.exception("Falha ao encerrar sorteio %s.", giveaway.id)

    @close_expired_giveaways.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(GiveawaysCog(bot))
