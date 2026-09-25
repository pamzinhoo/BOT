from __future__ import annotations

import io
from datetime import UTC, datetime

import discord
from discord.ext import commands, tasks

from core.bot import LimerenceBot
from core.logger import get_logger
from database.models.event_timer import EventTimer

logger = get_logger("event_timers")
_CHECK_INTERVAL_SECONDS = 60


def event_timer_embed(event: EventTimer) -> discord.Embed:
    unix_end = int(event.ends_at.timestamp())
    embed = discord.Embed(
        title=event.title,
        description=event.description or None,
        color=discord.Color.blurple(),
        timestamp=event.ends_at,
    )
    embed.add_field(name="Termina", value=f"<t:{unix_end}:F>", inline=True)
    embed.add_field(name="Tempo restante", value=f"<t:{unix_end}:R>", inline=True)
    embed.set_footer(text="Cronômetro de evento")
    if event.image_storage_path and event.image_filename:
        embed.set_image(url=f"attachment://{event.image_filename}")
    return embed


async def _delete_previous_message(bot: LimerenceBot, event: EventTimer) -> None:
    if event.message_id is None:
        return
    guild = bot.get_guild(event.guild_id)
    channel = guild.get_channel(event.channel_id) if guild else None
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        message = await channel.fetch_message(event.message_id)
        await message.delete()
    except discord.NotFound:
        pass
    except discord.HTTPException:
        logger.warning("Falha ao apagar mensagem anterior do evento %s.", event.id)


async def publish_event_timer(bot: LimerenceBot, event: EventTimer) -> int:
    guild = bot.get_guild(event.guild_id)
    if guild is None:
        raise RuntimeError("Servidor do evento nao esta disponivel.")
    channel = guild.get_channel(event.channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise RuntimeError("Canal do evento nao existe ou nao e textual.")

    await _delete_previous_message(bot, event)

    files: list[discord.File] = []
    image_bytes = await bot.event_timer_service.load_image(event)
    if image_bytes is not None and event.image_filename:
        files.append(discord.File(io.BytesIO(image_bytes), filename=event.image_filename))

    content = "@everyone" if event.mention_everyone else None
    allowed_mentions = discord.AllowedMentions(everyone=event.mention_everyone)
    message = await channel.send(
        content=content,
        embed=event_timer_embed(event),
        files=files,
        allowed_mentions=allowed_mentions,
    )
    return message.id


async def finish_event_timer(
    bot: LimerenceBot, event: EventTimer, *, canceled: bool = False
) -> None:
    await _delete_previous_message(bot, event)
    await bot.event_timer_service.finish(event.id, canceled=canceled)


class EventTimersCog(commands.Cog):
    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self.process_event_timers.start()

    def cog_unload(self) -> None:
        self.process_event_timers.cancel()

    @tasks.loop(seconds=_CHECK_INTERVAL_SECONDS)
    async def process_event_timers(self) -> None:
        now = datetime.now(UTC)
        for event in await self.bot.event_timer_service.list_expired(now):
            try:
                await finish_event_timer(self.bot, event)
            except Exception:
                logger.exception("Falha ao encerrar evento %s.", event.id)
        for due_event in await self.bot.event_timer_service.list_due(now):
            try:
                event = await self.bot.event_timer_service.claim_due(due_event.id, now)
                if event is None:
                    continue
                message_id = await publish_event_timer(self.bot, event)
                await self.bot.event_timer_service.mark_announced(event.id, message_id, now)
            except Exception as exc:
                logger.exception("Falha ao republicar evento %s.", due_event.id)
                await self.bot.event_timer_service.mark_error(due_event.id, str(exc))

        try:
            await self.bot.event_timer_service.retry_pending_image_cleanup()
        except Exception:
            logger.exception("Falha ao limpar imagens pendentes de cronometros.")

    @process_event_timers.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(EventTimersCog(bot))
