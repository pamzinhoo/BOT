from __future__ import annotations

import time
from datetime import datetime

import discord

from database.database import Database
from database.models.audit_log import AuditLogCategory, AuditLogEntry
from database.models.audit_log_settings import AuditLogSettings
from database.repositories.audit_log_repository import AuditLogRepository
from database.repositories.audit_log_settings_repository import AuditLogSettingsRepository
from utils.model_defaults import reset_row
from views.embeds import audit_log_embed

_AUDIT_LOOKUP_TTL_SECONDS = 5.0
_AUDIT_LOOKUP_MAX_AGE_SECONDS = 10.0


class AuditLogService:
    """Auditoria de eventos do servidor (bans/cargos/canais/voz/etc), paralela ao LogService
    de tickets. Cache curto evita bater duas vezes no audit log do Discord pro mesmo evento e
    evita reaproveitar a mesma entry do audit log em dois eventos diferentes."""

    def __init__(self, database: Database, bot: discord.Client) -> None:
        self._database = database
        self._bot = bot
        self._lookup_cache: dict[tuple[int, int, int | None], tuple[float, discord.AuditLogEntry | None]] = {}
        self._used_entry_ids: dict[int, float] = {}

    async def get_settings(self, guild_id: int) -> AuditLogSettings:
        async with self._database.session() as session:
            return await AuditLogSettingsRepository(session).get_or_create(guild_id)

    async def update_settings(self, guild_id: int, **fields: object) -> AuditLogSettings:
        async with self._database.session() as session:
            repo = AuditLogSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
            return settings

    async def reset_settings(self, guild_id: int) -> dict[str, tuple[object, object]]:
        """Restaura as categorias de auditoria (e o canal) pro padrão (Etapa 3)."""
        async with self._database.session() as session:
            settings = await AuditLogSettingsRepository(session).get_or_create(guild_id)
            return reset_row(settings)

    async def list_entries(
        self,
        guild_id: int,
        *,
        target_id: int | None = None,
        executor_id: int | None = None,
        category: AuditLogCategory | None = None,
        action: str | None = None,
        config_category: str | None = None,
        config_name: str | None = None,
        since: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[AuditLogEntry]:
        async with self._database.session() as session:
            return await AuditLogRepository(session).list_filtered(
                guild_id,
                target_id=target_id,
                executor_id=executor_id,
                category=category,
                action=action,
                config_category=config_category,
                config_name=config_name,
                since=since,
                limit=limit,
                offset=offset,
            )

    async def count_entries(
        self,
        guild_id: int,
        *,
        target_id: int | None = None,
        executor_id: int | None = None,
        category: AuditLogCategory | None = None,
        action: str | None = None,
        config_category: str | None = None,
        config_name: str | None = None,
        since: datetime | None = None,
    ) -> int:
        async with self._database.session() as session:
            return await AuditLogRepository(session).count_filtered(
                guild_id,
                target_id=target_id,
                executor_id=executor_id,
                category=category,
                action=action,
                config_category=config_category,
                config_name=config_name,
                since=since,
            )

    async def resolve_executor(
        self,
        guild: discord.Guild,
        audit_action: discord.AuditLogAction,
        *,
        target_id: int | None = None,
    ) -> discord.AuditLogEntry | None:
        now = time.monotonic()
        cache_key = (guild.id, audit_action.value, target_id)
        self._prune_cache(now)

        cached = self._lookup_cache.get(cache_key)
        if cached is not None:
            return cached[1]

        entry: discord.AuditLogEntry | None = None
        try:
            async for candidate in guild.audit_logs(limit=5, action=audit_action):
                age = (discord.utils.utcnow() - candidate.created_at).total_seconds()
                if age > _AUDIT_LOOKUP_MAX_AGE_SECONDS:
                    continue
                if target_id is not None and getattr(candidate.target, "id", None) != target_id:
                    continue
                if candidate.id in self._used_entry_ids:
                    continue
                entry = candidate
                break
        except discord.Forbidden:
            entry = None

        self._lookup_cache[cache_key] = (now, entry)
        if entry is not None:
            self._used_entry_ids[entry.id] = now
        return entry

    def _prune_cache(self, now: float) -> None:
        expired_keys = [
            key
            for key, (ts, _) in self._lookup_cache.items()
            if now - ts > _AUDIT_LOOKUP_TTL_SECONDS
        ]
        for key in expired_keys:
            del self._lookup_cache[key]
        expired_ids = [
            entry_id
            for entry_id, ts in self._used_entry_ids.items()
            if now - ts > _AUDIT_LOOKUP_TTL_SECONDS
        ]
        for entry_id in expired_ids:
            del self._used_entry_ids[entry_id]

    async def record(
        self,
        *,
        guild_id: int,
        category: AuditLogCategory,
        action: str,
        executor_id: int | None = None,
        executor_name: str | None = None,
        target_id: int | None = None,
        target_name: str | None = None,
        reason: str | None = None,
        details: dict[str, object] | None = None,
        config_category: str | None = None,
        config_name: str | None = None,
        old_value: str | None = None,
        new_value: str | None = None,
    ) -> AuditLogEntry | None:
        if executor_id is None and executor_name is None:
            executor_name = "Desconhecido"

        async with self._database.session() as session:
            settings = await AuditLogSettingsRepository(session).get_or_create(guild_id)
            if not getattr(settings, category.value):
                return None

            entry = await AuditLogRepository(session).add(
                AuditLogEntry(
                    guild_id=guild_id,
                    category=category,
                    action=action,
                    executor_id=executor_id,
                    executor_name=executor_name,
                    target_id=target_id,
                    target_name=target_name,
                    reason=reason,
                    details=details or {},
                    config_category=config_category,
                    config_name=config_name,
                    old_value=old_value,
                    new_value=new_value,
                )
            )
            channel_id = settings.channel_id

        if channel_id is not None:
            channel = self._bot.get_channel(channel_id)
            if isinstance(channel, discord.abc.Messageable):
                embed = audit_log_embed(
                    category,
                    action,
                    executor_name=executor_name,
                    executor_id=executor_id,
                    target_name=target_name,
                    target_id=target_id,
                    reason=reason,
                    details=details or {},
                    config_category=config_category,
                    config_name=config_name,
                    old_value=old_value,
                    new_value=new_value,
                )
                await channel.send(embed=embed)

        return entry

    async def record_config_change(
        self,
        *,
        guild_id: int,
        actor_id: int,
        actor_name: str,
        config_category: str,
        config_name: str,
        old_value: str,
        new_value: str,
    ) -> AuditLogEntry | None:
        """Grava uma alteracao feita via /config (slash command ou painel) no
        historico de auditoria. Nao grava se o valor nao mudou."""
        if old_value == new_value:
            return None
        return await self.record(
            guild_id=guild_id,
            category=AuditLogCategory.SERVER_CONFIG,
            action="Configuração alterada",
            executor_id=actor_id,
            executor_name=actor_name,
            config_category=config_category,
            config_name=config_name,
            old_value=old_value,
            new_value=new_value,
        )
