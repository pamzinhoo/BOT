from __future__ import annotations

import secrets
import string
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import discord

from core.logger import get_logger
from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.verification_session import VerificationSession, VerificationSessionStatus
from database.models.verification_settings import (
    CodeCharset,
    VerificationExceededAction,
    VerificationMethod,
    VerificationSettings,
)
from database.repositories.verification_session_repository import VerificationSessionRepository
from database.repositories.verification_settings_repository import VerificationSettingsRepository
from utils.time import humanize_duration

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("verification_service")

_RNG = secrets.SystemRandom()

DECOY_COUNT = 3
MIN_ATTEMPT_INTERVAL_SECONDS = 3

DEFAULT_WELCOME_MESSAGE = (
    "🛡️ **Verificação Necessária**\n\n"
    "Olá!\n\n"
    "Antes de entrar no nosso servidor, precisamos confirmar que você é uma pessoa real.\n\n"
    "Realize a verificação abaixo para liberar seu acesso.\n\n"
    "Essa etapa ajuda a proteger nossa comunidade contra bots e contas automatizadas.\n\n"
    "Assim que a verificação for concluída com sucesso, seu acesso será liberado automaticamente.\n\n"
    "Boa sorte! 💜"
)
DEFAULT_SUCCESS_MESSAGE = "✅ Verificação concluída com sucesso! Seu acesso foi liberado."
DEFAULT_ERROR_MESSAGE = "❌ Código incorreto. Tentativas restantes: {tentativas_restantes}."
DEFAULT_EXPIRED_MESSAGE = (
    "⌛ Sua verificação expirou. Entre em contato com a equipe caso precise de ajuda."
)
DEFAULT_MAX_ATTEMPTS_MESSAGE = "🚫 Você excedeu o número máximo de tentativas de verificação."

_ACTION_LABELS = {
    VerificationExceededAction.NONE: "Nenhuma ação",
    VerificationExceededAction.RESTART: "Verificação reiniciada",
    VerificationExceededAction.KICK: "Expulso",
    VerificationExceededAction.BAN: "Banido",
}

_METHOD_LABELS = {
    VerificationMethod.TYPE: "Digitar CAPTCHA",
    VerificationMethod.BUTTON: "Selecionar CAPTCHA",
}


def render_placeholders(template: str, **values: object) -> str:
    result = template
    for key, value in values.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


def _charset_pool(charset: CodeCharset) -> str:
    if charset == CodeCharset.LETTERS:
        return string.ascii_uppercase
    if charset == CodeCharset.NUMBERS:
        return string.digits
    return string.ascii_uppercase + string.digits


def generate_code(length: int, charset: CodeCharset) -> str:
    pool = _charset_pool(charset)
    return "".join(_RNG.choice(pool) for _ in range(length))


def generate_decoys(correct: str, charset: CodeCharset, *, count: int = DECOY_COUNT) -> list[str]:
    """Gera `count` codigos incorretos parecidos com o correto (1-2 caracteres
    trocados), pra dificultar a escolha por bots que so olham o formato."""
    pool = list(_charset_pool(charset))
    decoys: set[str] = set()
    for _ in range(200):
        if len(decoys) >= count:
            break
        candidate = list(correct)
        num_changes = min(_RNG.choice([1, 2]), len(candidate))
        for pos in _RNG.sample(range(len(candidate)), num_changes):
            candidate[pos] = _RNG.choice(pool)
        candidate_str = "".join(candidate)
        if candidate_str != correct:
            decoys.add(candidate_str)
    while len(decoys) < count:
        candidate_str = generate_code(len(correct), charset)
        if candidate_str != correct:
            decoys.add(candidate_str)
    return list(decoys)[:count]


def codes_match(submitted: str, expected: str, *, case_sensitive: bool) -> bool:
    if case_sensitive:
        return submitted == expected
    return submitted.strip().upper() == expected.strip().upper()


AttemptDecisionKind = Literal[
    "invalid_owner", "invalid_guild", "invalid_status", "stale", "expired", "cooldown", "success",
    "wrong", "max_attempts",
]


@dataclass
class AttemptDecision:
    kind: AttemptDecisionKind
    remaining: int | None = None
    wait_seconds: int | None = None


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def evaluate_attempt(
    *,
    record_user_id: int,
    record_guild_id: int,
    record_status: VerificationSessionStatus,
    record_generation: int,
    record_code: str,
    record_case_sensitive: bool,
    record_expires_at: datetime,
    record_last_attempt_at: datetime | None,
    record_attempts_used: int,
    record_max_attempts: int,
    guild_id: int | None,
    user_id: int,
    expected_generation: int | None,
    submitted: str,
    now: datetime,
) -> AttemptDecision:
    """Decisao pura (sem I/O) do que fazer com uma tentativa — usada por
    _process_attempt (que persiste o resultado) e diretamente pelos testes
    (sem precisar de banco). Nao muta nada, so decide."""
    if record_user_id != user_id:
        return AttemptDecision(kind="invalid_owner")
    if guild_id is not None and record_guild_id != guild_id:
        return AttemptDecision(kind="invalid_guild")
    if record_status != VerificationSessionStatus.PENDING:
        return AttemptDecision(kind="invalid_status")
    if expected_generation is not None and expected_generation != record_generation:
        return AttemptDecision(kind="stale")
    if now >= _as_utc(record_expires_at):
        return AttemptDecision(kind="expired")
    if record_last_attempt_at is not None:
        elapsed = (now - _as_utc(record_last_attempt_at)).total_seconds()
        if elapsed < MIN_ATTEMPT_INTERVAL_SECONDS:
            wait = int(MIN_ATTEMPT_INTERVAL_SECONDS - elapsed) + 1
            return AttemptDecision(kind="cooldown", wait_seconds=wait)
    if codes_match(submitted, record_code, case_sensitive=record_case_sensitive):
        return AttemptDecision(kind="success")
    remaining = record_max_attempts - (record_attempts_used + 1)
    if remaining <= 0:
        return AttemptDecision(kind="max_attempts", remaining=0)
    return AttemptDecision(kind="wrong", remaining=remaining)


OutcomeStatus = Literal[
    "success", "wrong", "cooldown", "expired", "max_attempts", "invalid", "stale"
]


@dataclass
class VerificationOutcome:
    status: OutcomeStatus
    message: str
    session: VerificationSession | None = None
    attempts_remaining: int | None = None


@dataclass
class VerificationPrompt:
    session: VerificationSession
    method: VerificationMethod
    code: str
    decoys: list[str] = field(default_factory=list)


class VerificationService:
    def __init__(self, database: Database, bot: LimerenceBot) -> None:
        self._database = database
        self._bot = bot

    # --- configuracao -----------------------------------------------------

    async def get_settings(self, guild_id: int) -> VerificationSettings:
        async with self._database.session() as session:
            return await VerificationSettingsRepository(session).get_or_create(guild_id)

    async def update_settings(self, guild_id: int, **fields: object) -> VerificationSettings:
        async with self._database.session() as session:
            repo = VerificationSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
            await session.flush()
            await session.refresh(settings)
        return settings

    # --- painel fixo (mensagem pinada em verification_channel_id) -----------

    async def publish_panel(self, guild_id: int) -> None:
        """Posta (ou reposta, se ja existia) a mensagem fixa de verificacao em
        verification_channel_id e fixa (pin) no canal. Chamado quando o canal
        e configurado/trocado em /config -> Verificação."""
        settings = await self.get_settings(guild_id)
        if settings.verification_channel_id is None:
            return
        guild = self._bot.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(settings.verification_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        from views.embeds import verification_panel_embed
        from views.verification_view import VerificationPanelView

        await self._delete_panel_message(settings)
        welcome = settings.welcome_message or DEFAULT_WELCOME_MESSAGE
        try:
            message = await channel.send(
                embed=verification_panel_embed(welcome), view=VerificationPanelView()
            )
        except discord.HTTPException:
            logger.warning("Falha ao publicar painel de verificação na guild %s.", guild_id)
            return
        with suppress(discord.HTTPException):
            await message.pin(reason="Painel fixo de verificação")
        await self.update_settings(guild_id, panel_message_id=message.id)

    async def refresh_panel(self, guild_id: int) -> None:
        """Reedita a mensagem fixa ja publicada (ex.: mudou a mensagem inicial
        ou o sistema foi ativado/desativado). Nunca reposta sozinho."""
        settings = await self.get_settings(guild_id)
        if settings.verification_channel_id is None or settings.panel_message_id is None:
            return
        guild = self._bot.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(settings.verification_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(settings.panel_message_id)
        except discord.HTTPException:
            return
        from views.embeds import verification_panel_embed

        welcome = settings.welcome_message or DEFAULT_WELCOME_MESSAGE
        with suppress(discord.HTTPException):
            await message.edit(embed=verification_panel_embed(welcome))

    async def _delete_panel_message(self, settings: VerificationSettings) -> None:
        if settings.verification_channel_id is None or settings.panel_message_id is None:
            return
        guild = self._bot.get_guild(settings.guild_id)
        if guild is None:
            return
        channel = guild.get_channel(settings.verification_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(settings.panel_message_id)
            await message.delete()
        except discord.HTTPException:
            pass

    # --- criacao de sessao --------------------------------------------------

    def _resolve_method(self, settings: VerificationSettings) -> VerificationMethod:
        configured = VerificationMethod(settings.method)
        if configured == VerificationMethod.RANDOM:
            return _RNG.choice([VerificationMethod.TYPE, VerificationMethod.BUTTON])
        return configured

    async def _build_session(
        self, guild_id: int, user_id: int, settings: VerificationSettings
    ) -> VerificationPrompt:
        method = self._resolve_method(settings)
        charset = CodeCharset(settings.code_charset)
        code = generate_code(settings.code_length, charset)
        decoys = generate_decoys(code, charset) if method == VerificationMethod.BUTTON else []
        now = datetime.now(UTC)
        async with self._database.session() as session:
            repo = VerificationSessionRepository(session)
            existing = await repo.get_pending_by_guild_user_locked(guild_id, user_id)
            if existing is not None:
                # ja existe uma verificacao em andamento — reaproveita a mesma
                # sessao (nao gera codigo novo) pra nao invalidar o progresso
                # de quem so reentrou/reabriu a DM.
                await session.refresh(existing)
                return VerificationPrompt(
                    session=existing, method=existing.method, code=existing.code, decoys=existing.decoys
                )

            record = await repo.add(
                VerificationSession(
                    guild_id=guild_id,
                    user_id=user_id,
                    method=method,
                    code=code,
                    case_sensitive=settings.case_sensitive,
                    decoys=decoys,
                    generation=1,
                    status=VerificationSessionStatus.PENDING,
                    attempts_used=0,
                    max_attempts=settings.max_attempts,
                    via_dm=True,
                    created_at=now,
                    expires_at=now + timedelta(minutes=settings.timeout_minutes),
                )
            )
            await session.flush()
            await session.refresh(record)
        return VerificationPrompt(session=record, method=method, code=code, decoys=decoys)

    async def start_verification(self, member: discord.Member) -> VerificationPrompt | None:
        """Chamado no on_member_join: aplica o cargo de nao-verificado e cria
        (ou reaproveita) a sessao de verificacao pra esse usuario. Devolve None
        se o sistema estiver desativado nessa guild."""
        settings = await self.get_settings(member.guild.id)
        if not settings.enabled:
            return None

        if settings.unverified_role_id is not None:
            role = member.guild.get_role(settings.unverified_role_id)
            if role is not None and role not in member.roles:
                try:
                    await member.add_roles(role, reason="Verificação: aguardando conclusão")
                except discord.HTTPException:
                    logger.warning(
                        "Falha ao aplicar cargo de não verificado na guild %s.", member.guild.id
                    )

        prompt = await self._build_session(member.guild.id, member.id, settings)

        await self._record_audit(
            guild_id=member.guild.id,
            action="Verificação iniciada",
            target_id=member.id,
            target_name=str(member),
            details={"método": _METHOD_LABELS.get(prompt.method, prompt.method.value)},
        )
        return prompt

    async def set_delivery(
        self, session_id: uuid.UUID, *, via_dm: bool, channel_id: int, message_id: int | None
    ) -> None:
        async with self._database.session() as session:
            record = await VerificationSessionRepository(session).get_by_id(session_id)
            if record is None:
                return
            record.via_dm = via_dm
            record.delivery_channel_id = channel_id
            record.message_id = message_id

    # --- tentativas ----------------------------------------------------------

    async def submit_type_attempt(
        self, *, session_id: uuid.UUID, guild_id: int | None, user_id: int, submitted_code: str
    ) -> VerificationOutcome:
        return await self._process_attempt(
            session_id=session_id,
            guild_id=guild_id,
            user_id=user_id,
            submitted=submitted_code,
            expected_generation=None,
        )

    async def submit_button_attempt(
        self,
        *,
        session_id: uuid.UUID,
        guild_id: int | None,
        user_id: int,
        generation: int,
        candidate: str,
    ) -> VerificationOutcome:
        return await self._process_attempt(
            session_id=session_id,
            guild_id=guild_id,
            user_id=user_id,
            submitted=candidate,
            expected_generation=generation,
        )

    async def _process_attempt(
        self,
        *,
        session_id: uuid.UUID,
        guild_id: int | None,
        user_id: int,
        submitted: str,
        expected_generation: int | None,
    ) -> VerificationOutcome:
        """Toda a mutacao do registro acontece dentro de UMA transacao curta
        (lock via get_by_id_locked). Efeitos colaterais que abrem sessoes
        proprias (cargos/kick/ban/log/reinicio) so rodam DEPOIS que essa
        transacao fecha — chama-los ainda dentro do `async with` prenderia a
        linha (FOR UPDATE) e uma sessao aninhada tentando ler/travar a mesma
        linha (ex.: reinicio automatico) ficaria esperando pra sempre."""
        now = datetime.now(UTC)
        # (tipo, registro, settings, acao) a executar apos a transacao fechar — so
        # preenchido quando a tentativa chega a um resultado terminal/relevante.
        post_commit: tuple[str, VerificationSession, VerificationSettings, VerificationExceededAction] | None = None

        try:
            async with self._database.session() as session:
                repo = VerificationSessionRepository(session)
                record = await repo.get_by_id_locked(session_id)
                if record is None:
                    return VerificationOutcome(status="invalid", message="Verificação não encontrada.")

                settings = await VerificationSettingsRepository(session).get_or_create(record.guild_id)

                decision = evaluate_attempt(
                    record_user_id=record.user_id,
                    record_guild_id=record.guild_id,
                    record_status=record.status,
                    record_generation=record.generation,
                    record_code=record.code,
                    record_case_sensitive=record.case_sensitive,
                    record_expires_at=record.expires_at,
                    record_last_attempt_at=record.last_attempt_at,
                    record_attempts_used=record.attempts_used,
                    record_max_attempts=record.max_attempts,
                    guild_id=guild_id,
                    user_id=user_id,
                    expected_generation=expected_generation,
                    submitted=submitted,
                    now=now,
                )

                if decision.kind == "invalid_owner":
                    return VerificationOutcome(
                        status="invalid", message="Este código de verificação não pertence a você."
                    )
                if decision.kind == "invalid_guild":
                    return VerificationOutcome(
                        status="invalid", message="Esta verificação não pertence a este servidor."
                    )
                if decision.kind == "invalid_status":
                    return VerificationOutcome(
                        status="invalid", message="Esse código já foi utilizado ou não está mais ativo."
                    )
                if decision.kind == "stale":
                    return VerificationOutcome(
                        status="stale",
                        message="Esse botão não é mais válido — um novo código foi gerado.",
                    )
                if decision.kind == "cooldown":
                    return VerificationOutcome(
                        status="cooldown", message=f"Aguarde {decision.wait_seconds}s antes de tentar novamente."
                    )

                if decision.kind == "expired":
                    record.status = VerificationSessionStatus.EXPIRED
                    record.completed_at = now
                    await session.flush()
                    await session.refresh(record)
                    message = settings.expired_message or DEFAULT_EXPIRED_MESSAGE
                    post_commit = (
                        "finalize", record, settings, VerificationExceededAction(settings.on_expire_action)
                    )
                    return VerificationOutcome(status="expired", message=message, session=record)

                record.last_attempt_at = now

                if decision.kind == "success":
                    record.status = VerificationSessionStatus.SUCCEEDED
                    record.completed_at = now
                    await session.flush()
                    await session.refresh(record)
                    message = settings.success_message or DEFAULT_SUCCESS_MESSAGE
                    post_commit = ("success", record, settings, VerificationExceededAction.NONE)
                    return VerificationOutcome(status="success", message=message, session=record)

                record.attempts_used += 1

                if decision.kind == "max_attempts":
                    record.status = VerificationSessionStatus.MAX_ATTEMPTS_EXCEEDED
                    record.completed_at = now
                    await session.flush()
                    await session.refresh(record)
                    message = settings.max_attempts_message or DEFAULT_MAX_ATTEMPTS_MESSAGE
                    post_commit = (
                        "finalize",
                        record,
                        settings,
                        VerificationExceededAction(settings.on_max_attempts_action),
                    )
                    return VerificationOutcome(status="max_attempts", message=message, session=record)

                # errou mas ainda tem tentativa — invalida o codigo atual e gera um novo
                remaining = decision.remaining
                charset = CodeCharset(settings.code_charset)
                new_code = generate_code(settings.code_length, charset)
                record.code = new_code
                record.decoys = (
                    generate_decoys(new_code, charset) if record.method == VerificationMethod.BUTTON else []
                )
                record.generation += 1
                await session.flush()
                await session.refresh(record)

                template = settings.error_message or DEFAULT_ERROR_MESSAGE
                message = render_placeholders(template, tentativas_restantes=remaining)
                post_commit = ("wrong_audit", record, settings, VerificationExceededAction.NONE)
                return VerificationOutcome(
                    status="wrong", message=message, session=record, attempts_remaining=remaining
                )
        finally:
            if post_commit is not None:
                kind, record, settings, action = post_commit
                if kind == "success":
                    await self._apply_success(record, settings)
                elif kind == "finalize":
                    label = (
                        "Expirado"
                        if record.status == VerificationSessionStatus.EXPIRED
                        else "Excedeu tentativas"
                    )
                    await self._finalize(record, settings, action, result_label=label)
                elif kind == "wrong_audit":
                    await self._record_audit(
                        guild_id=record.guild_id,
                        action="Tentativa de verificação incorreta",
                        target_id=record.user_id,
                        details={"tentativas_restantes": record.max_attempts - record.attempts_used},
                    )

    # --- expiracao (varredura periodica) -------------------------------------

    async def sweep_expired(self) -> int:
        now = datetime.now(UTC)
        processed = 0
        async with self._database.session() as session:
            expired = await VerificationSessionRepository(session).list_expired_pending(now)
            ids = [record.id for record in expired]

        for session_id in ids:
            async with self._database.session() as session:
                repo = VerificationSessionRepository(session)
                record = await repo.get_by_id_locked(session_id)
                if record is None or record.status != VerificationSessionStatus.PENDING:
                    continue
                expires_at = record.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if datetime.now(UTC) < expires_at:
                    continue
                record.status = VerificationSessionStatus.EXPIRED
                record.completed_at = datetime.now(UTC)
                await session.flush()
                await session.refresh(record)
                settings = await VerificationSettingsRepository(session).get_or_create(record.guild_id)

            action = VerificationExceededAction(settings.on_expire_action)
            await self._finalize(record, settings, action, result_label="Expirado")
            processed += 1
        return processed

    # --- efeitos colaterais (cargos/kick/ban/log) ---------------------------

    async def _get_member(self, guild_id: int, user_id: int) -> discord.Member | None:
        guild = self._bot.get_guild(guild_id)
        if guild is None:
            return None
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.NotFound:
            return None
        except discord.HTTPException:
            return None

    async def _apply_success(self, record: VerificationSession, settings: VerificationSettings) -> None:
        member = await self._get_member(record.guild_id, record.user_id)
        if member is not None:
            if settings.unverified_role_id is not None:
                role = member.guild.get_role(settings.unverified_role_id)
                if role is not None and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Verificação concluída")
                    except discord.HTTPException:
                        logger.warning("Falha ao remover cargo de não verificado (guild %s).", record.guild_id)
            if settings.verified_role_id is not None:
                role = member.guild.get_role(settings.verified_role_id)
                if role is not None and role not in member.roles:
                    try:
                        await member.add_roles(role, reason="Verificação concluída")
                    except discord.HTTPException:
                        logger.warning("Falha ao aplicar cargo de membro (guild %s).", record.guild_id)

        elapsed = None
        if record.completed_at is not None:
            elapsed = int((record.completed_at - record.created_at).total_seconds())
        await self._record_audit(
            guild_id=record.guild_id,
            action="Verificação aprovada",
            target_id=record.user_id,
            target_name=str(member) if member else None,
            details={
                "método": _METHOD_LABELS.get(record.method, record.method.value),
                "tentativas": record.attempts_used,
                "tempo_gasto": humanize_duration(elapsed),
            },
        )
        await self._send_log(record, result_label="✅ Aprovado", elapsed_seconds=elapsed)

    async def _finalize(
        self,
        record: VerificationSession,
        settings: VerificationSettings,
        action: VerificationExceededAction,
        *,
        result_label: str,
    ) -> None:
        member = await self._get_member(record.guild_id, record.user_id)
        reason = f"Verificação: {result_label.lower()}"

        if action == VerificationExceededAction.RESTART:
            if member is not None:
                await self.start_verification(member)
        elif action == VerificationExceededAction.KICK and member is not None:
            try:
                await member.kick(reason=reason)
            except discord.HTTPException:
                logger.warning("Falha ao expulsar %s na guild %s (verificação).", record.user_id, record.guild_id)
        elif action == VerificationExceededAction.BAN and member is not None:
            try:
                await member.ban(reason=reason, delete_message_seconds=0)
            except discord.HTTPException:
                logger.warning("Falha ao banir %s na guild %s (verificação).", record.user_id, record.guild_id)

        elapsed = None
        if record.completed_at is not None:
            elapsed = int((record.completed_at - record.created_at).total_seconds())

        category_action = {
            VerificationExceededAction.NONE: "Verificação encerrada",
            VerificationExceededAction.RESTART: "Verificação reiniciada",
            VerificationExceededAction.KICK: "Usuário expulso (verificação)",
            VerificationExceededAction.BAN: "Usuário banido (verificação)",
        }[action]
        await self._record_audit(
            guild_id=record.guild_id,
            action=category_action,
            target_id=record.user_id,
            target_name=str(member) if member else None,
            details={
                "resultado": result_label,
                "tentativas": record.attempts_used,
                "tempo_gasto": humanize_duration(elapsed),
                "ação": _ACTION_LABELS[action],
            },
        )
        await self._send_log(
            record, result_label=f"{result_label} ({_ACTION_LABELS[action]})", elapsed_seconds=elapsed
        )

    async def _send_log(
        self, record: VerificationSession, *, result_label: str, elapsed_seconds: int | None
    ) -> None:
        settings = await self.get_settings(record.guild_id)
        if settings.log_channel_id is None:
            return
        guild = self._bot.get_guild(record.guild_id)
        if guild is None:
            return
        channel = guild.get_channel(settings.log_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return

        from views.embeds import verification_log_embed

        try:
            await channel.send(
                embed=verification_log_embed(
                    user_id=record.user_id,
                    method_label=_METHOD_LABELS.get(record.method, record.method.value),
                    attempts_used=record.attempts_used,
                    max_attempts=record.max_attempts,
                    elapsed_label=humanize_duration(elapsed_seconds),
                    result_label=result_label,
                )
            )
        except discord.HTTPException:
            logger.exception("Falha ao enviar log de verificação na guild %s.", record.guild_id)

    async def _record_audit(
        self,
        *,
        guild_id: int,
        action: str,
        target_id: int | None = None,
        target_name: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        await self._bot.audit_log_service.record(
            guild_id=guild_id,
            category=AuditLogCategory.VERIFICATION,
            action=action,
            target_id=target_id,
            target_name=target_name,
            details=details or {},
        )
