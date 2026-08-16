from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

import discord

from database.models.log import LogAction
from services.evaluation_service import EvaluationError
from utils.achievements import announce_achievements
from utils.constants import EMBED_COLOR_DEFAULT
from views.base_view import SafeView
from views.embeds import evaluation_thanks_message

if TYPE_CHECKING:
    from core.bot import LimerenceBot


class _DMCommentModal(discord.ui.Modal, title="Deixe um comentário (opcional)"):
    comment: discord.ui.TextInput[_DMCommentModal] = discord.ui.TextInput(
        label="Comentário", style=discord.TextStyle.paragraph, required=False, max_length=500
    )

    def __init__(self, ticket_id: uuid.UUID, rating: int, min_comment_rating: int | None = 2) -> None:
        super().__init__()
        self.ticket_id = ticket_id
        self.rating = rating
        if min_comment_rating is not None and rating <= min_comment_rating:
            self.title = "Conte o que deu errado"
            self.comment.required = True
            self.comment.label = "O que podemos melhorar? (obrigatório)"
            self.comment.placeholder = "Nota baixa precisa de um motivo."

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await _submit_dm(interaction, self.ticket_id, self.rating, str(self.comment) or None)


async def _submit_dm(
    interaction: discord.Interaction, ticket_id: uuid.UUID, rating: int, comment: str | None
) -> None:
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    # Deferir de imediato: submit_evaluation_by_ticket_id, ticket_service.get_by_id,
    # log_service.record, refresh_dashboard e o envio pro canal de avaliacoes sao
    # varias idas ao banco/rede antes de termos uma resposta pra mostrar, o que
    # facilmente passa dos 3s que o Discord da pra responder a interacao.
    await interaction.response.defer()

    try:
        result = await bot.evaluation_service.submit_evaluation_by_ticket_id(
            ticket_id, interaction.user.id, rating, comment
        )
    except EvaluationError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    evaluation = result.evaluation

    ticket = await bot.ticket_service.get_by_id(ticket_id)
    guild_id = ticket.guild_id if ticket is not None else None
    star = "⭐"
    thanks_message = f"Obrigado pela avaliação: {star * rating}"

    if guild_id is not None:
        eval_settings = await bot.config_service.get_evaluation_settings(guild_id)
        star = eval_settings.star_emoji
        guild = bot.get_guild(guild_id)
        thanks_message = evaluation_thanks_message(
            eval_settings,
            member=interaction.user,
            guild=guild,
            ticket_id=str(ticket_id)[:8],
        )
        await bot.log_service.record(
            guild_id=guild_id,
            action=LogAction.AVALIACAO,
            actor_discord_id=interaction.user.id,
            staff_id=evaluation.staff_id,
            ticket_id=evaluation.ticket_id,
            message=f"Ticket avaliado com {rating} estrela(s) por DM (canal já excluído).",
        )
        await bot.painel_service.refresh_dashboard(guild_id)

        settings = await bot.config_service.get_settings(guild_id)
        if settings.evaluations_channel_id is not None:
            eval_channel = bot.get_channel(settings.evaluations_channel_id)
            if isinstance(eval_channel, discord.TextChannel):
                staff = await bot.staff_service.get_by_id(evaluation.staff_id)
                embed = discord.Embed(
                    title=f"{star} Nova avaliação (via DM)",
                    description=(
                        f"**Staff:** {staff.display_name if staff else '—'}\n"
                        f"**Avaliado por:** {interaction.user.mention} ({interaction.user})\n"
                        f"**Nota:** {star * rating}\n"
                        f"**Comentário:** {comment or '—'}"
                    ),
                    color=EMBED_COLOR_DEFAULT,
                )
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
                await eval_channel.send(embed=embed)

        if isinstance(interaction.channel, discord.DMChannel):
            await announce_achievements(
                bot, interaction.channel, evaluation.staff_id, result.unlocked_achievements
            )

    await interaction.followup.send(thanks_message, ephemeral=True)


class DMEvaluationView(SafeView):
    """Avaliacao mandada por DM — usada tanto quando `evaluation_method` da
    guild inclui DM (fluxo principal, ver `views/ticket_actions_view.py`)
    quanto no fallback historico (staff exclui o ticket antes do usuario
    avaliar pelo canal). O ticket_id nao vem de `channel_id` (o canal do
    ticket pode nao existir mais quando o usuario finalmente clica), entao
    cada botao carrega o `ticket_id` no proprio custom_id.

    Persistent (timeout=None) — os botoes sao `DMRatingButton`, um
    `discord.ui.DynamicItem` com custom_id ESTAVEL
    (`limerence:eval_dm:<ticket_id>:<rating>`), registrado uma unica vez no
    boot (`core.bot.LimerenceBot._register_persistent_views`) via
    `add_dynamic_items` — continua funcionando depois de qualquer restart,
    nao importa quando o usuario finalmente decidir avaliar."""

    def __init__(self, ticket_id: uuid.UUID) -> None:
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        for rating in range(1, 6):
            self.add_item(DMRatingButton(ticket_id, rating))


class DMRatingButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"limerence:eval_dm:(?P<ticket_id>[0-9a-fA-F-]{36}):(?P<rating>[1-5])",
):
    def __init__(self, ticket_id: uuid.UUID, rating: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="⭐" * rating,
                style=discord.ButtonStyle.secondary,
                custom_id=f"limerence:eval_dm:{ticket_id}:{rating}",
            )
        )
        self.ticket_id = ticket_id
        self.rating = rating

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]
    ) -> DMRatingButton:
        return cls(uuid.UUID(match["ticket_id"]), int(match["rating"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        min_comment_rating = None
        ticket = await bot.ticket_service.get_by_id(self.ticket_id)
        if ticket is not None:
            eval_settings = await bot.config_service.get_evaluation_settings(ticket.guild_id)
            min_comment_rating = eval_settings.min_comment_rating
        await interaction.response.send_modal(
            _DMCommentModal(self.ticket_id, self.rating, min_comment_rating)
        )
