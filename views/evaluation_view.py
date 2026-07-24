from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from database.models.log import LogAction
from services.evaluation_service import EvaluationError
from utils.achievements import announce_achievements
from utils.constants import EMBED_COLOR_DEFAULT
from utils.ticket_lifecycle import schedule_channel_deletion

if TYPE_CHECKING:
    from core.bot import LimerenceBot


class _CommentModal(discord.ui.Modal, title="Deixe um comentário (opcional)"):
    comment: discord.ui.TextInput[_CommentModal] = discord.ui.TextInput(
        label="Comentário", style=discord.TextStyle.paragraph, required=False, max_length=500
    )

    def __init__(self, rating: int, min_comment_rating: int | None = 2) -> None:
        super().__init__()
        self.rating = rating
        if min_comment_rating is not None and rating <= min_comment_rating:
            self.title = "Conte o que deu errado"
            self.comment.required = True
            self.comment.label = "O que podemos melhorar? (obrigatório)"
            self.comment.placeholder = "Nota baixa precisa de um motivo."

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await _submit(interaction, self.rating, str(self.comment) or None)


async def _submit(interaction: discord.Interaction, rating: int, comment: str | None) -> None:
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    guild = interaction.guild
    if guild is None or interaction.channel_id is None:
        return

    try:
        result = await bot.evaluation_service.submit_evaluation(
            interaction.channel_id, interaction.user.id, rating, comment
        )
    except EvaluationError as exc:
        if interaction.response.is_done():
            await interaction.followup.send(str(exc), ephemeral=True)
        else:
            await interaction.response.send_message(str(exc), ephemeral=True)
        return
    evaluation = result.evaluation

    await bot.log_service.record(
        guild_id=guild.id,
        action=LogAction.AVALIACAO,
        actor_discord_id=interaction.user.id,
        staff_id=evaluation.staff_id,
        ticket_id=evaluation.ticket_id,
        message=f"Ticket avaliado com {rating} estrela(s).",
    )
    await bot.painel_service.refresh_dashboard(guild.id)

    settings = await bot.config_service.get_settings(guild.id)
    eval_settings = await bot.config_service.get_evaluation_settings(guild.id)
    star = eval_settings.star_emoji
    if settings.evaluations_channel_id is not None:
        eval_channel = bot.get_channel(settings.evaluations_channel_id)
        if isinstance(eval_channel, discord.TextChannel):
            staff = await bot.staff_service.get_by_id(evaluation.staff_id)
            embed = discord.Embed(
                title=f"{star} Nova avaliação",
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

    channel = interaction.channel
    if isinstance(channel, discord.TextChannel):
        await announce_achievements(bot, channel, evaluation.staff_id, result.unlocked_achievements)

    message = f"Obrigado pela avaliação: {star * rating}"
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)

    if isinstance(channel, discord.TextChannel):
        schedule_channel_deletion(channel, "avaliação recebida")


class EvaluationView(discord.ui.View):
    """1-5 estrelas. Persistent (timeout=None); resolve o ticket pelo channel_id."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        for rating in range(1, 6):
            self.add_item(_RatingButton(rating))


class _RatingButton(discord.ui.Button["EvaluationView"]):
    def __init__(self, rating: int) -> None:
        super().__init__(
            label="⭐" * rating,
            style=discord.ButtonStyle.secondary,
            custom_id=f"limerence:eval:{rating}",
        )
        self.rating = rating

    async def callback(self, interaction: discord.Interaction) -> None:
        min_comment_rating = None
        if interaction.guild_id is not None:
            bot: LimerenceBot = interaction.client  # type: ignore[assignment]
            eval_settings = await bot.config_service.get_evaluation_settings(interaction.guild_id)
            min_comment_rating = eval_settings.min_comment_rating
        await interaction.response.send_modal(_CommentModal(self.rating, min_comment_rating))
