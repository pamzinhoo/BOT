from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord

from core.logger import get_logger
from database.database import Database
from database.models.booster import Booster
from database.models.booster_settings import BoosterSettings
from database.repositories.booster_repository import BoosterRepository
from database.repositories.booster_settings_repository import BoosterSettingsRepository
from utils.ttl_cache import TTLCache

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("booster_service")

# mesmo padrao/janela ja usado em ConfigService/AutoModService/AuditLogService
# — settings mudam so quando staff edita via /config, reconcile_guild (cron
# 1h) senao rebuscava do zero por membro divergente.
_SETTINGS_TTL_SECONDS = 300.0

DEFAULT_DM_MESSAGE = (
    "💜 Obrigado por impulsionar {server_name}!\n\n"
    "Seu apoio ajuda nossa comunidade a crescer cada vez mais.\n\n"
    "Você recebeu o cargo {role_name}."
)

DEFAULT_PUBLIC_MESSAGE = (
    "🎉 Muito obrigado {user} por impulsionar o servidor!\n\n"
    "Sua ajuda significa muito para nossa comunidade! 💜"
)


def render_placeholders(
    template: str, *, member: discord.Member, role: discord.Role | None, boost_count: int
) -> str:
    return (
        template
        .replace("{user}", member.mention)
        .replace("{server_name}", member.guild.name)
        .replace("{role_name}", role.mention if role is not None else "—")
        .replace("{boost_count}", str(boost_count))
        .replace("{member_count}", str(member.guild.member_count))
    )


class BoosterService:
    """Sistema de Boosters (modulo comercial): detecta boost via premium_since no
    on_member_update (nunca via mensagens automaticas do Discord), entrega/remove
    cargo, persiste historico e dispara DM/mensagem publica/log configuraveis."""

    def __init__(self, database: Database, bot: LimerenceBot) -> None:
        self._database = database
        self._bot = bot
        self._settings_cache: TTLCache[int, BoosterSettings] = TTLCache(_SETTINGS_TTL_SECONDS)

    # --- configuracao ---------------------------------------------------

    async def get_settings(self, guild_id: int) -> BoosterSettings:
        cached = self._settings_cache.get(guild_id)
        if cached is not None:
            return cached
        async with self._database.session() as session:
            settings = await BoosterSettingsRepository(session).get_or_create(guild_id)
        self._settings_cache.set(guild_id, settings)
        return settings

    async def update_settings(self, guild_id: int, **fields: object) -> BoosterSettings:
        async with self._database.session() as session:
            repo = BoosterSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
            await session.flush()
            await session.refresh(settings)
        self._settings_cache.invalidate(guild_id)
        return settings

    # --- historico (base pro futuro Hall dos Boosters/ranking) -----------------

    async def list_boosters(self, guild_id: int, limit: int = 100) -> list[Booster]:
        async with self._database.session() as session:
            return await BoosterRepository(session).list_by_guild(guild_id, limit)

    # --- reconciliacao periodica -------------------------------------------

    async def reconcile_guild(self, guild: discord.Guild) -> None:
        """on_member_update e a unica fonte oficial de deteccao de boost, mas se
        o bot ficar offline exatamente durante o inicio/fim de um boost (deploy,
        crash, gap de resume do gateway) esse evento nunca chega — o membro
        ficaria com o cargo/beneficio pra sempre (ou nunca receberia). Chamado
        periodicamente pra comparar guild.premium_subscribers (fonte de verdade
        do Discord) contra o que esta marcado como currently_boosting no banco,
        corrigindo qualquer divergencia via os mesmos handlers idempotentes do
        evento normal."""
        settings = await self.get_settings(guild.id)
        if not settings.enabled:
            return

        actually_boosting_ids = {member.id for member in guild.premium_subscribers}

        async with self._database.session() as session:
            tracked = await BoosterRepository(session).list_active_by_guild(guild.id)
        tracked_ids = {record.user_id for record in tracked}

        for user_id in tracked_ids - actually_boosting_ids:
            member = guild.get_member(user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except discord.NotFound:
                    continue
                except discord.HTTPException:
                    logger.warning(
                        "Falha ao buscar membro %s na guild %s durante reconciliacao de boosters.",
                        user_id, guild.id,
                    )
                    continue
            await self.handle_boost_removed(member)

        for member in guild.premium_subscribers:
            if member.id not in tracked_ids:
                await self.handle_boost_started(member)

    # --- fluxo: boost iniciado -------------------------------------------------

    async def handle_boost_started(self, member: discord.Member) -> None:
        settings = await self.get_settings(member.guild.id)
        if not settings.enabled:
            return

        async with self._database.session() as session:
            repo = BoosterRepository(session)
            record = await repo.get_by_guild_user_locked(member.guild.id, member.id)
            if record is not None and record.currently_boosting:
                return  # ja processado — evita duplicar cargo/DM em atualizacoes redundantes

            now = datetime.now(UTC)
            if record is None:
                record = await repo.add(
                    Booster(
                        guild_id=member.guild.id,
                        user_id=member.id,
                        boost_since=now,
                        boost_count=1,
                        currently_boosting=True,
                    )
                )
            else:
                record.boost_since = now
                record.boost_count += 1
                record.currently_boosting = True
            await session.flush()
            await session.refresh(record)
            boost_count = record.boost_count

        role = member.guild.get_role(settings.booster_role_id) if settings.booster_role_id else None
        if role is not None and role not in member.roles:
            try:
                await member.add_roles(role, reason="Booster: cargo de impulsionador entregue")
            except discord.Forbidden:
                logger.warning(
                    "Sem permissão para entregar cargo de booster na guild %s.", member.guild.id
                )
            except discord.HTTPException:
                logger.exception("Falha ao entregar cargo de booster na guild %s.", member.guild.id)

        if settings.dm_enabled:
            await self._send_dm(member, settings, role, boost_count)

        if settings.public_message_enabled:
            await self._send_public_message(member, settings, role, boost_count)

        await self._send_log_added(member, settings, role, boost_count)

    # --- fluxo: boost removido -------------------------------------------------

    async def handle_boost_removed(self, member: discord.Member) -> None:
        settings = await self.get_settings(member.guild.id)
        if not settings.enabled:
            return

        async with self._database.session() as session:
            repo = BoosterRepository(session)
            record = await repo.get_by_guild_user_locked(member.guild.id, member.id)
            if record is None or not record.currently_boosting:
                return  # nunca registrado como boosting — nada a reverter

            now = datetime.now(UTC)
            duration_seconds = (
                int((now - record.boost_since).total_seconds()) if record.boost_since else None
            )
            record.currently_boosting = False
            record.last_removed = now
            await session.flush()

        role = member.guild.get_role(settings.booster_role_id) if settings.booster_role_id else None
        if role is not None and role in member.roles:
            try:
                await member.remove_roles(role, reason="Booster: impulsionamento removido")
            except discord.Forbidden:
                logger.warning(
                    "Sem permissão para remover cargo de booster na guild %s.", member.guild.id
                )
            except discord.HTTPException:
                logger.exception("Falha ao remover cargo de booster na guild %s.", member.guild.id)

        await self._send_log_removed(member, settings, role, duration_seconds)

    # --- notificacoes -----------------------------------------------------

    async def _send_dm(
        self,
        member: discord.Member,
        settings: BoosterSettings,
        role: discord.Role | None,
        boost_count: int,
    ) -> None:
        template = settings.dm_message or DEFAULT_DM_MESSAGE
        content = render_placeholders(template, member=member, role=role, boost_count=boost_count)
        try:
            await member.send(content)
        except discord.Forbidden:
            pass  # DM fechada — ignora o erro e segue o fluxo normalmente
        except discord.HTTPException:
            logger.exception("Falha ao enviar DM de booster para %s.", member.id)

    async def _send_public_message(
        self,
        member: discord.Member,
        settings: BoosterSettings,
        role: discord.Role | None,
        boost_count: int,
    ) -> None:
        if settings.public_channel_id is None:
            return
        channel = member.guild.get_channel(settings.public_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return
        template = settings.public_message or DEFAULT_PUBLIC_MESSAGE
        content = render_placeholders(template, member=member, role=role, boost_count=boost_count)
        try:
            if settings.public_use_embed:
                from utils.constants import EMBED_COLOR_PURPLE

                await channel.send(embed=discord.Embed(description=content, color=EMBED_COLOR_PURPLE))
            else:
                await channel.send(content)
        except discord.HTTPException:
            logger.exception("Falha ao enviar mensagem pública de booster na guild %s.", member.guild.id)

    async def _send_log_added(
        self,
        member: discord.Member,
        settings: BoosterSettings,
        role: discord.Role | None,
        boost_count: int,
    ) -> None:
        if settings.log_channel_id is None:
            return
        channel = member.guild.get_channel(settings.log_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return
        from views.embeds import booster_added_log_embed

        try:
            await channel.send(embed=booster_added_log_embed(member, role, boost_count))
        except discord.HTTPException:
            logger.exception("Falha ao enviar log de booster adicionado na guild %s.", member.guild.id)

    async def _send_log_removed(
        self,
        member: discord.Member,
        settings: BoosterSettings,
        role: discord.Role | None,
        duration_seconds: int | None,
    ) -> None:
        if settings.log_channel_id is None:
            return
        channel = member.guild.get_channel(settings.log_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return
        from views.embeds import booster_removed_log_embed

        try:
            await channel.send(embed=booster_removed_log_embed(member, role, duration_seconds))
        except discord.HTTPException:
            logger.exception("Falha ao enviar log de booster removido na guild %s.", member.guild.id)
