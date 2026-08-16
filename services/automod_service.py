from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import discord

from database.database import Database
from database.models.automod import (
    AutoModCategory,
    AutoModLog,
    AutoModRiskLevel,
    AutoModSettings,
    AutoModWord,
)
from database.repositories.automod_repository import (
    AutoModLogRepository,
    AutoModSettingsRepository,
    AutoModWordRepository,
)
from utils.automod_wordlist import (
    CONTEXT_SENSITIVE_WORDS,
    CRITICAL_WORDS,
    DEFAULT_WORDS_BY_TEXT,
    compact_form,
    normalize_text,
)
from utils.ttl_cache import TTLCache

# mesma janela ja usada por ConfigService pros settings mais lidos
# (guild_settings/ticket_settings/permission_settings/anti_spam_settings) —
# settings e lista de palavras do AutoMod mudam so quando um staff edita
# via comando, entao 5 minutos de defasagem maxima e aceitavel e mantem o
# mesmo padrao de risco ja usado no resto do bot, em vez de inventar um TTL novo.
_AUTOMOD_CACHE_TTL_SECONDS = 300.0


class AutoModError(ValueError):
    """Erro de negocio no AutoMod (mostrado direto pro staff)."""


@dataclass
class EffectiveWord:
    palavra: str
    categoria: AutoModCategory
    nivel: AutoModRiskLevel
    is_builtin: bool


@dataclass
class AutoModMatch:
    palavra: str
    categoria: AutoModCategory
    nivel: AutoModRiskLevel
    context_only: bool = False  # True = termo sensivel ao contexto (ex.: "preto"), nao pune sozinho


@dataclass
class AutoModDecision:
    match: AutoModMatch
    action: str  # rotulo salvo em automod_logs.punicao_aplicada
    message_deleted: bool
    timeout_applied: bool
    banned: bool
    alerted_mods: bool


# rotulos de acao aplicada, usados no log e nos embeds
ACTION_NONE = "nenhuma"
ACTION_FLAGGED = "sinalizada_para_revisao"
ACTION_WARN = "apagar_mensagem+aviso"
ACTION_TIMEOUT = "apagar_mensagem+timeout"
ACTION_BAN = "apagar_mensagem+ban"


class AutoModService:
    def __init__(self, database: Database) -> None:
        self._database = database
        # escopo por guild, igual ConfigService — nunca mistura guilds
        # diferentes, cada uma tem sua propria entrada/expiracao.
        self._settings_cache: TTLCache[int, AutoModSettings] = TTLCache(
            _AUTOMOD_CACHE_TTL_SECONDS
        )
        self._words_cache: TTLCache[int, list[EffectiveWord]] = TTLCache(
            _AUTOMOD_CACHE_TTL_SECONDS
        )

    # --- configuracao ---------------------------------------------------

    async def get_settings(self, guild_id: int) -> AutoModSettings:
        cached = self._settings_cache.get(guild_id)
        if cached is not None:
            return cached
        async with self._database.session() as session:
            settings = await AutoModSettingsRepository(session).get_or_create(guild_id)
        self._settings_cache.set(guild_id, settings)
        return settings

    async def update_settings(self, guild_id: int, **fields: object) -> AutoModSettings:
        async with self._database.session() as session:
            repo = AutoModSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
            await session.flush()
            await session.refresh(settings)
        self._settings_cache.invalidate(guild_id)
        return settings

    async def set_enabled(self, guild_id: int, enabled: bool) -> AutoModSettings:
        return await self.update_settings(guild_id, enabled=enabled)

    # --- palavras ---------------------------------------------------------

    async def add_word(
        self,
        guild_id: int,
        palavra: str,
        *,
        categoria: AutoModCategory = AutoModCategory.PERSONALIZADA,
        nivel: AutoModRiskLevel = AutoModRiskLevel.BAIXO,
        added_by_id: int | None = None,
    ) -> AutoModWord:
        normalized = normalize_text(palavra)
        if not normalized:
            raise AutoModError("Palavra inválida.")
        async with self._database.session() as session:
            repo = AutoModWordRepository(session)
            existing = await repo.get_by_word(guild_id, normalized)
            if existing is not None:
                existing.categoria = categoria
                existing.nivel = nivel
                existing.is_builtin = False
                existing.active = True
                await session.flush()
                await session.refresh(existing)
                self._words_cache.invalidate(guild_id)
                return existing
            word = await repo.add(
                AutoModWord(
                    guild_id=guild_id,
                    palavra=normalized,
                    categoria=categoria,
                    nivel=nivel,
                    is_builtin=False,
                    active=True,
                    added_by_id=added_by_id,
                )
            )
            await session.flush()
            await session.refresh(word)
        self._words_cache.invalidate(guild_id)
        return word

    async def remove_word(self, guild_id: int, palavra: str) -> bool:
        """Remove uma palavra personalizada, ou cria um override de supressao
        se a palavra fizer parte da lista padrao embutida no código."""
        normalized = normalize_text(palavra)
        async with self._database.session() as session:
            repo = AutoModWordRepository(session)
            existing = await repo.get_by_word(guild_id, normalized)
            if existing is not None and not existing.is_builtin:
                await repo.delete(existing)
                self._words_cache.invalidate(guild_id)
                return True
            if existing is not None and existing.is_builtin:
                if not existing.active:
                    return False
                existing.active = False
                await session.flush()
                self._words_cache.invalidate(guild_id)
                return True
            if normalized not in DEFAULT_WORDS_BY_TEXT:
                return False
            categoria, nivel = DEFAULT_WORDS_BY_TEXT[normalized]
            await repo.add(
                AutoModWord(
                    guild_id=guild_id,
                    palavra=normalized,
                    categoria=categoria,
                    nivel=nivel,
                    is_builtin=True,
                    active=False,
                )
            )
            await session.flush()
        self._words_cache.invalidate(guild_id)
        return True

    async def list_effective_words(self, guild_id: int) -> list[EffectiveWord]:
        """Lista padrao embutida + overrides da guild (personalizadas e supressoes).
        Cacheada por guild — so muda quando `add_word`/`remove_word` roda (os
        dois invalidam a entrada), entao o resultado nao fica obsoleto por
        muito alem do TTL de qualquer jeito."""
        cached = self._words_cache.get(guild_id)
        if cached is not None:
            return list(cached)

        async with self._database.session() as session:
            overrides = await AutoModWordRepository(session).list_by_guild(guild_id)

        overrides_by_word = {o.palavra: o for o in overrides}
        result: list[EffectiveWord] = []
        for word, (categoria, nivel) in DEFAULT_WORDS_BY_TEXT.items():
            override = overrides_by_word.get(word)
            if override is not None and override.is_builtin and not override.active:
                continue  # suprimida pela guild
            result.append(EffectiveWord(word, categoria, nivel, is_builtin=True))
        for override in overrides:
            if not override.is_builtin and override.active:
                result.append(
                    EffectiveWord(override.palavra, override.categoria, override.nivel, is_builtin=False)
                )
        effective = sorted(result, key=lambda w: w.palavra)
        self._words_cache.set(guild_id, effective)
        return list(effective)

    # --- logs ---------------------------------------------------------

    async def list_logs(self, guild_id: int, limit: int = 20) -> list[AutoModLog]:
        async with self._database.session() as session:
            return await AutoModLogRepository(session).list_recent(guild_id, limit)

    # --- deteccao ---------------------------------------------------------

    def analyze(self, content: str, words: list[EffectiveWord], allowed_words: list[str]) -> AutoModMatch | None:
        """Encontra a ocorrencia de maior gravidade na mensagem, ou None."""
        normalized = normalize_text(content)
        if not normalized:
            return None
        compact = compact_form(normalized)
        allowed_normalized = {normalize_text(w) for w in allowed_words}

        matches: list[AutoModMatch] = []
        for word in words:
            if word.palavra in allowed_normalized:
                continue
            if " " in word.palavra:
                hit = f" {word.palavra} " in f" {normalized} "
            else:
                hit = (
                    f" {word.palavra} " in f" {normalized} "
                    or (len(word.palavra) >= 4 and word.palavra in compact)
                )
            if not hit:
                continue

            context_only = word.palavra in CONTEXT_SENSITIVE_WORDS
            matches.append(AutoModMatch(word.palavra, word.categoria, word.nivel, context_only=context_only))

        if not matches:
            return None

        # contexto: se um termo sensivel (preto/negro) aparece junto com outro termo
        # discriminatorio/ofensivo real na mesma mensagem, deixa de ser "so suspeita"
        # e escala pro nivel do termo discriminatorio (evita falso positivo isolado).
        non_context = [m for m in matches if not m.context_only]
        if non_context:
            return max(non_context, key=lambda m: _LEVEL_WEIGHT[m.nivel])

        return matches[0]

    async def evaluate_message(self, message: discord.Message) -> AutoModDecision | None:
        if message.guild is None or message.author.bot:
            return None
        if not isinstance(message.author, discord.Member):
            return None

        settings = await self.get_settings(message.guild.id)
        if not settings.enabled:
            return None
        if message.channel.id in settings.ignored_channel_ids:
            return None
        member_role_ids = {role.id for role in message.author.roles}
        if member_role_ids & set(settings.ignored_role_ids):
            return None

        words = await self.list_effective_words(message.guild.id)
        match = self.analyze(message.content or "", words, settings.allowed_words)
        if match is None:
            return None

        if match.context_only:
            await self._write_log_db(message, match, ACTION_FLAGGED)
            return AutoModDecision(
                match=match, action=ACTION_FLAGGED, message_deleted=False,
                timeout_applied=False, banned=False, alerted_mods=False,
            )

        return await self._apply_action(message, match, settings)

    async def _apply_action(
        self, message: discord.Message, match: AutoModMatch, settings: AutoModSettings
    ) -> AutoModDecision:
        assert isinstance(message.author, discord.Member)
        member = message.author
        deleted = False
        timeout_applied = False
        banned = False
        alerted = False

        try:
            await message.delete()
            deleted = True
        except discord.HTTPException:
            pass

        if match.nivel == AutoModRiskLevel.BAIXO:
            action = ACTION_WARN
            try:
                warning = await message.channel.send(
                    f"{member.mention} sua mensagem foi removida por conter conteúdo impróprio.",
                )
                await warning.delete(delay=8)
            except discord.HTTPException:
                pass

        elif match.nivel == AutoModRiskLevel.MEDIO:
            action = ACTION_TIMEOUT
            timeout_applied = await self._try_timeout(member, settings.medio_timeout_minutes)

        else:  # ALTO
            if settings.alto_use_ban:
                action = ACTION_BAN
                banned = await self._try_ban(message.guild, member, match)
            else:
                action = ACTION_TIMEOUT
                timeout_applied = await self._try_timeout(member, settings.alto_timeout_minutes)
            alerted = await self._alert_mods(message, match, settings)

        await self._write_log_db(message, match, action)
        return AutoModDecision(
            match=match, action=action, message_deleted=deleted,
            timeout_applied=timeout_applied, banned=banned, alerted_mods=alerted,
        )

    @staticmethod
    async def _try_timeout(member: discord.Member, minutes: int) -> bool:
        try:
            await member.timeout(timedelta(minutes=minutes), reason="AutoMod: conteúdo proibido detectado")
            return True
        except discord.HTTPException:
            return False

    @staticmethod
    async def _try_ban(guild: discord.Guild, member: discord.Member, match: AutoModMatch) -> bool:
        try:
            await guild.ban(
                member, reason=f"AutoMod: conteúdo de alto risco detectado ({match.categoria.value})",
                delete_message_seconds=0,
            )
            return True
        except discord.HTTPException:
            return False

    @staticmethod
    async def _alert_mods(
        message: discord.Message, match: AutoModMatch, settings: AutoModSettings
    ) -> bool:
        if settings.alert_channel_id is None:
            return False
        channel = message.guild.get_channel(settings.alert_channel_id) if message.guild else None
        if not isinstance(channel, discord.abc.Messageable):
            return False
        urgent = " 🚨 CONTEÚDO CRÍTICO" if match.palavra in CRITICAL_WORDS else ""
        try:
            await channel.send(
                f"⚠️ AutoMod (alto risco{urgent}): {message.author.mention} em <#{message.channel.id}> "
                f"— categoria `{match.categoria.value}`, termo detectado sinalizado nos logs."
            )
            return True
        except discord.HTTPException:
            return False

    async def _write_log_db(self, message: discord.Message, match: AutoModMatch, action: str) -> None:
        assert message.guild is not None
        async with self._database.session() as session:
            await AutoModLogRepository(session).add(
                AutoModLog(
                    guild_id=message.guild.id,
                    user_id=message.author.id,
                    user_name=str(message.author),
                    channel_id=message.channel.id,
                    message_id=message.id,
                    mensagem=(message.content or "")[:500],
                    palavra_detectada=match.palavra,
                    categoria=match.categoria,
                    nivel=match.nivel,
                    punicao_aplicada=action,
                )
            )


_LEVEL_WEIGHT = {
    AutoModRiskLevel.BAIXO: 0,
    AutoModRiskLevel.MEDIO: 1,
    AutoModRiskLevel.ALTO: 2,
}
