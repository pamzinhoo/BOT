from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import discord

from database.database import Database
from database.models.social_notification import (
    SocialNotification,
    SocialNotificationStatus,
    SocialPlatform,
)
from database.repositories.social_notification_repository import SocialNotificationRepository

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_MAX_MESSAGE_LENGTH = 2000
_MAX_URL_LENGTH = 2048
_PLATFORM_HOSTS: dict[SocialPlatform, tuple[str, ...]] = {
    SocialPlatform.YOUTUBE: ("youtube.com", "youtu.be"),
    SocialPlatform.TIKTOK: ("tiktok.com",),
    SocialPlatform.INSTAGRAM: ("instagram.com",),
    SocialPlatform.TWITCH: ("twitch.tv",),
    SocialPlatform.KICK: ("kick.com",),
}

_PLACEHOLDER_RE = re.compile(r"\{url\}", re.IGNORECASE)


class SocialNotificationValidationError(ValueError):
    pass


def detect_platform(url: str) -> SocialPlatform:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for platform, hosts in _PLATFORM_HOSTS.items():
        if host == platform.value or any(
            host == item or host.endswith(f".{item}") for item in hosts
        ):
            return platform
    return SocialPlatform.OTHER


def render_message(template: str, url: str) -> str:
    message = _PLACEHOLDER_RE.sub(url, template.strip())
    if not message:
        message = url
    if len(message) > _MAX_MESSAGE_LENGTH:
        raise SocialNotificationValidationError(
            f"A mensagem final precisa ter no maximo {_MAX_MESSAGE_LENGTH} caracteres."
        )
    return message


class SocialNotificationService:
    """Envio imediato de avisos sociais e historico reutilizavel pelo monitor automatico."""

    def __init__(self, database: Database, bot: LimerenceBot) -> None:
        self._database = database
        self._bot = bot

    @staticmethod
    def validate_url(raw_url: str) -> str:
        url = raw_url.strip()
        parsed = urlparse(url)
        if (
            len(url) > _MAX_URL_LENGTH
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
        ):
            raise SocialNotificationValidationError("Informe uma URL http:// ou https:// valida.")
        return url

    async def list_by_guild(self, guild_id: int) -> list[SocialNotification]:
        async with self._database.session() as session:
            return await SocialNotificationRepository(session).list_by_guild(guild_id)

    async def send_manual(
        self,
        *,
        guild_id: int,
        creator_id: int,
        channel_id: int,
        url: str,
        message_template: str,
        mention_everyone: bool,
    ) -> SocialNotification:
        clean_url = self.validate_url(url)
        if len(message_template.strip()) > _MAX_MESSAGE_LENGTH:
            raise SocialNotificationValidationError(
                "A mensagem nao pode ultrapassar 2000 caracteres."
            )
        message_content = render_message(message_template, clean_url)

        guild = self._bot.get_guild(guild_id)
        if guild is None:
            raise SocialNotificationValidationError("Servidor nao encontrado ou nao carregado.")
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise SocialNotificationValidationError("Escolha um canal de texto valido.")
        me = guild.me
        if me is None:
            raise SocialNotificationValidationError(
                "Nao foi possivel localizar o bot neste servidor."
            )
        permissions = channel.permissions_for(me)
        if not permissions.send_messages:
            raise SocialNotificationValidationError(
                "O bot nao tem permissao para enviar mensagens nesse canal."
            )
        if mention_everyone and not permissions.mention_everyone:
            raise SocialNotificationValidationError(
                "O bot nao tem permissao para mencionar @everyone nesse canal."
            )

        notification: SocialNotification | None = None
        async with self._database.session() as session:
            repo = SocialNotificationRepository(session)
            notification = await repo.add(
                SocialNotification(
                    guild_id=guild_id,
                    creator_id=creator_id,
                    channel_id=channel_id,
                    platform=detect_platform(clean_url),
                    url=clean_url,
                    message_template=message_template.strip(),
                    mention_everyone=mention_everyone,
                    status=SocialNotificationStatus.FAILED,
                )
            )
            await session.refresh(notification)

        allowed_mentions = discord.AllowedMentions(everyone=mention_everyone)
        try:
            sent = await channel.send(message_content, allowed_mentions=allowed_mentions)
        except discord.Forbidden as exc:
            await self._mark_failed(notification.id, "Discord recusou o envio por permissao.")
            raise SocialNotificationValidationError(
                "Discord recusou o envio por permissao."
            ) from exc
        except discord.HTTPException as exc:
            await self._mark_failed(notification.id, "Discord recusou o envio da mensagem.")
            raise SocialNotificationValidationError("Discord recusou o envio da mensagem.") from exc

        async with self._database.session() as session:
            current = await SocialNotificationRepository(session).get_by_id(notification.id)
            if current is not None:
                current.message_id = sent.id
                current.status = SocialNotificationStatus.SENT
                current.error_message = None
                await session.flush()
                await session.refresh(current)
                return current
        raise RuntimeError("Notificacao criada mas nao encontrada apos o envio.")

    async def _mark_failed(self, notification_id, error: str) -> None:
        async with self._database.session() as session:
            current = await SocialNotificationRepository(session).get_by_id(notification_id)
            if current is not None:
                current.status = SocialNotificationStatus.FAILED
                current.error_message = error[:1000]
                await session.flush()
