from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.bot import LimerenceBot
from core.logger import get_logger
from database.models.audit_log import AuditLogCategory
from database.models.poll import PollOption
from services.poll_service import AlreadyVotedError, EnqueteDisabledError, InvalidOptionsError
from utils.checks import is_admin
from utils.time import InvalidDurationError, parse_duration
from views.base_view import SafeView
from views.embeds import poll_creation_embed, poll_results_embed

logger = get_logger("polls")

_CHECK_INTERVAL_MINUTES = 5


class PollVoteButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"poll:vote:(?P<poll_id>[0-9a-fA-F-]{36}):(?P<option_id>[0-9a-fA-F-]{36})",
):
    """Botao persistente de voto — 1 por opcao. Sobrevive a restart do bot;
    numero de opcoes varia por enquete, entao nao da pra usar add_view estatico."""

    def __init__(self, poll_id: uuid.UUID, option_id: uuid.UUID, label: str) -> None:
        super().__init__(
            discord.ui.Button(
                label=label[:80],
                style=discord.ButtonStyle.secondary,
                custom_id=f"poll:vote:{poll_id}:{option_id}",
            )
        )
        self.poll_id = poll_id
        self.option_id = option_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: Any
    ) -> PollVoteButton:
        return cls(uuid.UUID(match["poll_id"]), uuid.UUID(match["option_id"]), label="Votar")

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        member = interaction.user
        if not isinstance(member, discord.Member):
            return

        # Defere de imediato: get_poll/can_vote/cast_vote sao chamadas ao
        # banco que podem passar dos 3s de prazo do Discord antes da 1a
        # resposta, num botao publico de voto.
        await interaction.response.defer()

        poll = await bot.poll_service.get_poll(self.poll_id)
        if poll is None or poll.guild_id != interaction.guild_id:
            await interaction.followup.send("Enquete não encontrada.", ephemeral=True)
            return

        can_vote, reason = await bot.poll_service.can_vote(poll, member)
        if not can_vote:
            await interaction.followup.send(
                reason or "Você não pode votar nessa enquete.", ephemeral=True
            )
            return

        try:
            vote = await bot.poll_service.cast_vote(poll, self.option_id, member)
        except AlreadyVotedError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        await interaction.followup.send(
            f"✅ Voto registrado com peso **{vote.weight}**.", ephemeral=True
        )


class PollVoteView(SafeView):
    def __init__(self, poll_id: uuid.UUID, options: list[PollOption]) -> None:
        super().__init__(timeout=None)
        for option in options:
            self.add_item(PollVoteButton(poll_id, option.id, option.name))


class _EnqueteCreateModal(discord.ui.Modal, title="Criar Enquete"):
    descricao: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Descrição",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )
    opcoes: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Opções (1 por linha, mín. 2, máx. 10)",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500,
    )
    duracao: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Duração (ex: 24h, 30m, 7d)",
        required=True,
        max_length=10,
        default="24h",
    )

    def __init__(self, titulo: str, canal: discord.TextChannel) -> None:
        super().__init__()
        self.titulo = titulo
        self.canal = canal

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]

        # Defere de imediato: create_poll + canal.send + set_message_id +
        # audit_log_service.record abaixo sao varias chamadas que podem
        # passar dos 3s de prazo do Discord antes da 1a resposta.
        await interaction.response.defer(ephemeral=True)

        try:
            duration = parse_duration(str(self.duracao.value))
        except InvalidDurationError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        options = str(self.opcoes.value).splitlines()
        try:
            poll, created_options = await bot.poll_service.create_poll(
                guild_id=interaction.guild_id,
                creator_id=interaction.user.id,
                channel_id=self.canal.id,
                title=self.titulo,
                description=str(self.descricao.value).strip() or None,
                options=options,
                duration=duration,
            )
        except (EnqueteDisabledError, InvalidOptionsError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        view = PollVoteView(poll.id, created_options)
        message = await self.canal.send(embed=poll_creation_embed(poll, created_options), view=view)
        await bot.poll_service.set_message_id(poll.id, message.id)

        await bot.audit_log_service.record(
            guild_id=interaction.guild_id,
            category=AuditLogCategory.ENQUETE,
            action="ENQUETE_CRIADA",
            executor_id=interaction.user.id,
            executor_name=str(interaction.user),
            details={"poll_id": str(poll.id), "title": poll.title, "options": [o.name for o in created_options]},
        )

        await interaction.followup.send(f"Enquete criada em {self.canal.mention}!", ephemeral=True)


class PollsCog(commands.Cog):
    """Sistema de Enquetes com peso de voto. Toda regra de negocio vive em
    PollService/VoteWeightService — esta Cog so recebe comandos/eventos e
    delega, seguindo o mesmo padrao das outras Cogs do bot."""

    enquete_group = app_commands.Group(
        name="enquete", description="Sistema de enquetes com peso de voto."
    )

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self.close_expired_polls.start()

    def cog_unload(self) -> None:
        self.close_expired_polls.cancel()

    @enquete_group.command(name="criar", description="Cria uma nova enquete com peso de voto.")
    @app_commands.describe(titulo="Título da enquete", canal="Canal onde a enquete será postada")
    @is_admin()
    async def criar(
        self, interaction: discord.Interaction, titulo: str, canal: discord.TextChannel
    ) -> None:
        await interaction.response.send_modal(_EnqueteCreateModal(titulo, canal))

    @tasks.loop(minutes=_CHECK_INTERVAL_MINUTES)
    async def close_expired_polls(self) -> None:
        now = datetime.now(UTC)
        for poll in await self.bot.poll_service.list_open_expiring(now):
            try:
                await self._close_and_announce(poll.id)
            except Exception:
                logger.exception("Falha ao encerrar enquete %s.", poll.id)

    @close_expired_polls.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _close_and_announce(self, poll_id: uuid.UUID) -> None:
        options = await self.bot.poll_service.list_options(poll_id)
        totals = await self.bot.poll_service.weighted_totals(poll_id)
        participants = await self.bot.poll_service.count_participants(poll_id)
        closed = await self.bot.poll_service.close_poll(poll_id)
        if closed is None:
            return

        guild = self.bot.get_guild(closed.guild_id)
        if guild is None:
            return
        channel = guild.get_channel(closed.channel_id)

        if closed.message_id is not None and isinstance(channel, discord.abc.Messageable):
            try:
                message = await channel.fetch_message(closed.message_id)
                await message.edit(view=None)
            except discord.HTTPException:
                pass

        if isinstance(channel, discord.abc.Messageable):
            try:
                await channel.send(embed=poll_results_embed(closed, options, totals, participants))
            except discord.HTTPException:
                logger.exception("Falha ao enviar resultado da enquete %s.", closed.id)

        await self.bot.audit_log_service.record(
            guild_id=closed.guild_id,
            category=AuditLogCategory.ENQUETE,
            action="ENQUETE_ENCERRADA",
            details={
                "poll_id": str(closed.id),
                "title": closed.title,
                "totals": {str(option_id): total for option_id, total in totals.items()},
                "participants": participants,
            },
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if {role.id for role in before.roles} == {role.id for role in after.roles}:
            return
        try:
            await self.bot.poll_service.on_member_role_change(after)
        except Exception:
            logger.exception(
                "Falha ao processar mudança de cargo pra enquetes na guild %s.", after.guild.id
            )


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(PollsCog(bot))
