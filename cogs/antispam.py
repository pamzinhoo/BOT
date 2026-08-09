from __future__ import annotations

import hashlib
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import discord
from discord.ext import commands

from core.bot import LimerenceBot
from core.logger import get_logger
from database.models.anti_spam_settings import AntiSpamSettings
from database.models.log import LogAction
from utils.checks import member_has_staff_role
from utils.constants import EMBED_COLOR_WARNING
from views.blacklist_action_view import BlacklistActionView

logger = get_logger("antispam")

# defaults quando a guild nao configurou nada — mesmos valores de antes de virar configuravel
_REPORT_COOLDOWN_SECONDS = 120
_MAX_ATTACHMENT_BYTES = 8_000_000
_MIN_TEXT_LENGTH = 6


@dataclass
class _Occurrence:
    author_id: int
    channel_id: int
    jump_url: str
    at: datetime


@dataclass
class _SignatureBuffer:
    occurrences: list[_Occurrence] = field(default_factory=list)


class AntiSpamCog(commands.Cog):
    """Detecta a mesma mensagem/imagem repetida em varios canais (padrao
    classico de conta comprometida) ou em flood no mesmo canal, e reporta
    pro canal de blacklist com botoes de acao pra staff."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self._buffers: dict[str, _SignatureBuffer] = {}
        self._last_reported: dict[str, datetime] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        if not isinstance(message.author, discord.Member) or not isinstance(
            message.channel, discord.TextChannel
        ):
            return

        settings = await self.bot.config_service.get_settings(message.guild.id)
        if settings.blacklist_channel_id is None:
            return
        anti_spam = await self.bot.config_service.get_anti_spam_settings(message.guild.id)
        if anti_spam.ignore_staff and member_has_staff_role(message.author, settings):
            return

        signature, image_url = await self._signature_for(message)
        if signature is None:
            return
        # a assinatura e so o hash do conteudo (sem guild_id) — texto/imagem de
        # spam costuma ser identico entre servidores diferentes, entao a chave
        # do buffer PRECISA incluir a guild pra nao misturar ocorrencias (e
        # vazar canais/usuarios) de um servidor no alerta de outro.
        signature = f"{message.guild.id}:{signature}"

        now = message.created_at
        buffer = self._buffers.setdefault(signature, _SignatureBuffer())
        buffer.occurrences.append(
            _Occurrence(message.author.id, message.channel.id, message.jump_url, now)
        )
        self._prune(buffer, now, anti_spam.window_seconds)

        distinct_channels = {occ.channel_id for occ in buffer.occurrences}
        same_channel_recent = [
            occ
            for occ in buffer.occurrences
            if occ.author_id == message.author.id
            and occ.channel_id == message.channel.id
            and (now - occ.at).total_seconds() <= anti_spam.flood_window_seconds
        ]
        same_author_total = [occ for occ in buffer.occurrences if occ.author_id == message.author.id]

        reason = None
        if len(distinct_channels) >= anti_spam.cross_channel_threshold:
            reason = (
                f"O mesmo conteúdo apareceu em {len(distinct_channels)} canais diferentes "
                f"em menos de {anti_spam.window_seconds}s — padrão típico de conta comprometida."
            )
        elif len(same_channel_recent) >= anti_spam.flood_threshold:
            reason = (
                f"{len(same_channel_recent)} mensagens repetidas no mesmo canal "
                f"em menos de {anti_spam.flood_window_seconds}s — flood."
            )
        elif len(same_author_total) >= anti_spam.repeat_threshold:
            reason = (
                f"Mesmo autor repetiu o mesmo conteúdo {len(same_author_total)}x em "
                f"{anti_spam.window_seconds}s — continua mandando spam mesmo após alerta anterior."
            )

        if reason is None:
            return

        # cooldown so evita reportar a MESMA ocorrencia de novo em sequencia — nao bloqueia
        # detectar um novo padrao (ex: rajada nova) nem deixa o autor sumir do radar por muito tempo
        report_key = f"{signature}:{message.author.id}"
        last_reported = self._last_reported.get(report_key)
        if last_reported is not None and (now - last_reported).total_seconds() < _REPORT_COOLDOWN_SECONDS:
            return

        self._last_reported[report_key] = now
        try:
            await self._report(message, settings.blacklist_channel_id, buffer, reason, image_url, anti_spam)
        except Exception:
            logger.exception("Falha ao reportar spam na guild %s.", message.guild.id)

    @staticmethod
    def _prune(buffer: _SignatureBuffer, now: datetime, window_seconds: int) -> None:
        cutoff = now - timedelta(seconds=window_seconds)
        buffer.occurrences = [occ for occ in buffer.occurrences if occ.at >= cutoff]

    @staticmethod
    async def _signature_for(message: discord.Message) -> tuple[str | None, str | None]:
        if message.attachments:
            attachment = message.attachments[0]
            if attachment.size <= _MAX_ATTACHMENT_BYTES:
                try:
                    data = await attachment.read()
                except discord.HTTPException:
                    data = None
                if data:
                    digest = hashlib.sha256(data).hexdigest()
                    return f"file:{digest}", attachment.url

        content = (message.content or "").strip().lower()
        normalized = " ".join(content.split())
        if len(normalized) >= _MIN_TEXT_LENGTH:
            digest = hashlib.sha256(normalized.encode()).hexdigest()
            return f"text:{digest}", None

        return None, None

    async def _report(
        self,
        message: discord.Message,
        blacklist_channel_id: int,
        buffer: _SignatureBuffer,
        reason: str,
        image_url: str | None,
        anti_spam: AntiSpamSettings,
    ) -> None:
        assert message.guild is not None
        channel = self.bot.get_channel(blacklist_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        other_authors = {occ.author_id for occ in buffer.occurrences} - {message.author.id}
        channels_hit = sorted({occ.channel_id for occ in buffer.occurrences})
        links = [
            f"<#{cid}>" for cid in channels_hit[:6]
        ]

        embed = discord.Embed(
            title="🚨 Possível spam detectado",
            description=reason,
            color=EMBED_COLOR_WARNING,
        )
        embed.add_field(name="Autor", value=f"{message.author.mention} (`{message.author.id}`)", inline=False)
        if other_authors:
            embed.add_field(
                name="Outros envolvidos",
                value=", ".join(f"<@{uid}>" for uid in list(other_authors)[:6]),
                inline=False,
            )
        embed.add_field(name="Canais atingidos", value=" ".join(links) or "—", inline=False)
        if message.content:
            excerpt = message.content[:300]
            embed.add_field(name="Conteúdo", value=f"```{excerpt}```", inline=False)
        embed.add_field(name="Mensagem original", value=f"[Ir até a mensagem]({message.jump_url})", inline=False)
        if image_url:
            embed.set_image(url=image_url)
        embed.set_footer(text=f"Ticket automático de antispam — {datetime.now(UTC).strftime('%d/%m/%Y %H:%M')}")

        view = BlacklistActionView(target_user_id=message.author.id, guild_id=message.guild.id)
        await channel.send(embed=embed, view=view)

        if anti_spam.default_action == "apagar_mensagem":
            with suppress(discord.HTTPException):
                await message.delete()

        await self.bot.log_service.record(
            guild_id=message.guild.id,
            action=LogAction.SPAM_DETECTADO,
            actor_discord_id=message.author.id,
            message=f"Spam detectado: {reason}",
        )


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(AntiSpamCog(bot))
