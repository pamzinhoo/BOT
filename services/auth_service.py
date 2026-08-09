from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import quote

import aiohttp

from config.settings import Settings
from core.logger import get_logger
from core.rate_limiter import RateLimiter, RateLimitExceeded
from core.security import jwt_service
from core.security.tokens import (
    PKCEPair,
    generate_device_code,
    generate_pkce_pair,
    generate_refresh_token,
    generate_state,
    generate_user_code,
    hash_token,
)
from database.database import Database
from database.models.audit_log_launcher import AuditLogLauncherAction
from database.models.device import Device
from database.models.launcher_session import LauncherSession
from database.repositories.audit_log_launcher_repository import AuditLogLauncherRepository
from database.repositories.device_repository import DeviceRepository
from database.repositories.launcher_session_repository import LauncherSessionRepository
from database.repositories.player_repository import PlayerRepository

logger = get_logger("auth_service")

_DISCORD_API_BASE = "https://discord.com/api/v10"
_DEVICE_CODE_TTL_SECONDS = 600
_POLL_MIN_INTERVAL_SECONDS = 5
_JWT_KEY_ID = "v1"

PollStatus = Literal["authorization_pending", "slow_down", "success", "expired_token", "access_denied"]


class AuthError(Exception):
    """Erro de negocio do fluxo de auth — a rota decide o status HTTP a partir de `code`."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(slots=True)
class _PendingLogin:
    device_code: str
    user_code: str
    device_uuid: uuid.UUID
    os_info: str | None
    launcher_version: str | None
    pkce: PKCEPair
    state: str
    created_at: datetime
    expires_at: datetime
    status: Literal["pending", "completed", "denied"] = "pending"
    last_poll_at: datetime | None = None
    tokens: TokenPair | None = None


@dataclass(frozen=True, slots=True)
class DeviceCodeIssued:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"


@dataclass(frozen=True, slots=True)
class PollResult:
    status: PollStatus
    tokens: TokenPair | None = None
    interval: int | None = None


class AuthService:
    """Orquestra o login Discord -> Launcher sem que o Launcher jamais veja
    client_secret ou token do Discord (ver bot/docs/AUTH_API_CONTRACT.md).

    O estado do device-flow (`_PendingLogin`) e mantido em memoria, nao no
    banco: e efemero (~10min), de uso unico, e a API roda embarcada no bot
    como instancia unica (sem Redis no stack) — nao ha necessidade de
    persistir isso entre reinicios.
    """

    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings
        self._pending_logins: dict[str, _PendingLogin] = {}
        self._state_to_device_code: dict[str, str] = {}
        self._lock = asyncio.Lock()

        self._device_code_limiter = RateLimiter(max_hits=10, window_seconds=300)
        self._poll_limiter = RateLimiter(max_hits=120, window_seconds=300)
        self._refresh_limiter = RateLimiter(max_hits=30, window_seconds=60)
        self._logout_limiter = RateLimiter(max_hits=20, window_seconds=60)
        self._callback_limiter = RateLimiter(max_hits=30, window_seconds=300)

    async def _audit(
        self,
        *,
        action: AuditLogLauncherAction,
        player_id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Grava um evento de auditoria em sessao propria — usado quando o
        evento acontece fora de uma transacao ja aberta (ex.: falha na troca
        de codigo com o Discord, antes de qualquer Player/Device existir)."""
        async with self._database.session() as session:
            await AuditLogLauncherRepository(session).record(
                action=action, player_id=player_id, device_id=device_id, ip_address=ip_address, metadata=metadata
            )

    async def enforce_rate_limit(self, bucket: str, key: str) -> None:
        limiter = {
            "device_code": self._device_code_limiter,
            "poll": self._poll_limiter,
            "refresh": self._refresh_limiter,
            "logout": self._logout_limiter,
            "callback": self._callback_limiter,
        }[bucket]
        try:
            await limiter.hit(key)
        except RateLimitExceeded:
            logger.warning("Rate limit excedido: bucket=%s key=%s", bucket, key)
            raise

    # ------------------------------------------------------------------
    # Passo 1: Launcher pede device_code/user_code
    # ------------------------------------------------------------------
    async def create_device_login(
        self,
        *,
        device_uuid: uuid.UUID,
        os_info: str | None,
        launcher_version: str | None,
    ) -> DeviceCodeIssued:
        now = datetime.now(UTC)
        pending = _PendingLogin(
            device_code=generate_device_code(),
            user_code=generate_user_code(),
            device_uuid=device_uuid,
            os_info=os_info,
            launcher_version=launcher_version,
            pkce=generate_pkce_pair(),
            state=generate_state(),
            created_at=now,
            expires_at=now + timedelta(seconds=_DEVICE_CODE_TTL_SECONDS),
        )
        async with self._lock:
            self._purge_expired_locked()
            self._pending_logins[pending.device_code] = pending
            self._state_to_device_code[pending.state] = pending.device_code

        verification_uri = f"{self._settings.public_base_url}/auth/device/authorize?user_code={pending.user_code}"
        return DeviceCodeIssued(
            device_code=pending.device_code,
            user_code=pending.user_code,
            verification_uri=verification_uri,
            expires_in=_DEVICE_CODE_TTL_SECONDS,
            interval=_POLL_MIN_INTERVAL_SECONDS,
        )

    def _purge_expired_locked(self) -> None:
        now = datetime.now(UTC)
        expired = [code for code, p in self._pending_logins.items() if p.expires_at < now]
        for code in expired:
            pending = self._pending_logins.pop(code)
            self._state_to_device_code.pop(pending.state, None)

    # ------------------------------------------------------------------
    # Passo 2: navegador abre a pagina de autorizacao do backend
    # ------------------------------------------------------------------
    async def build_discord_authorize_url(self, *, user_code: str) -> str:
        async with self._lock:
            self._purge_expired_locked()
            pending = next(
                (p for p in self._pending_logins.values() if p.user_code == user_code.upper()), None
            )
            if pending is None or pending.status != "pending":
                raise AuthError("invalid_user_code", "Codigo invalido ou expirado.")

        params = {
            "client_id": self._settings.discord_oauth_client_id,
            "redirect_uri": self._settings.discord_oauth_redirect_uri,
            "response_type": "code",
            "scope": "identify",
            "state": pending.state,
            "code_challenge": pending.pkce.challenge,
            "code_challenge_method": pending.pkce.challenge_method,
            "prompt": "consent",
        }
        query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
        return f"https://discord.com/oauth2/authorize?{query}"

    # ------------------------------------------------------------------
    # Passo 3: Discord redireciona de volta pro backend
    # ------------------------------------------------------------------
    async def handle_discord_callback(self, *, code: str, state: str, ip: str | None) -> None:
        async with self._lock:
            self._purge_expired_locked()
            device_code = self._state_to_device_code.get(state)
            pending = self._pending_logins.get(device_code) if device_code else None
            if pending is None or pending.status != "pending":
                raise AuthError("invalid_state", "Sessao de login invalida ou expirada.")

        try:
            discord_id, discord_username = await self._exchange_and_fetch_discord_user(
                code=code, code_verifier=pending.pkce.verifier
            )
        except Exception:
            logger.exception("Falha ao trocar codigo com o Discord (device_code=%s)", pending.device_code)
            async with self._lock:
                pending.status = "denied"
            await self._audit(
                action=AuditLogLauncherAction.LOGIN_FAILED,
                ip_address=ip,
                metadata={"reason": "discord_exchange_failed"},
            )
            raise AuthError("discord_exchange_failed", "Nao foi possivel confirmar o login com o Discord.")

        now = datetime.now(UTC)
        async with self._database.session() as session:
            player = await PlayerRepository(session).get_or_create_by_discord_id(
                discord_id, discord_username=discord_username, linked_at=now
            )
            player.last_login_at = now
            player.last_login_ip = ip

            device_repo = DeviceRepository(session)
            device = await device_repo.get_by_player_and_uuid(player.id, pending.device_uuid)
            if device is None:
                device = Device(
                    player_id=player.id,
                    device_uuid=pending.device_uuid,
                    os_info=pending.os_info,
                    launcher_version=pending.launcher_version,
                    first_seen_at=now,
                    last_seen_at=now,
                    last_ip=ip,
                )
                await device_repo.add(device)
            else:
                if device.revoked:
                    raise AuthError("device_revoked", "Este dispositivo foi revogado.")
                device.last_seen_at = now
                device.last_ip = ip
                if pending.launcher_version:
                    device.launcher_version = pending.launcher_version

            await session.flush()

            refresh_token = generate_refresh_token()
            launcher_session = LauncherSession(
                device_id=device.id,
                refresh_token_hash=hash_token(refresh_token),
                jwt_key_id=_JWT_KEY_ID,
                issued_at=now,
                expires_at=now + timedelta(days=self._settings.refresh_token_ttl_days),
                last_used_at=now,
                last_ip=ip,
            )
            await LauncherSessionRepository(session).add(launcher_session)
            await session.flush()

            access_token = jwt_service.encode_access_token(
                player_id=player.id,
                device_id=device.id,
                session_id=launcher_session.id,
                secret_key=self._settings.jwt_secret_key,
                ttl_seconds=self._settings.jwt_access_ttl_seconds,
                key_id=_JWT_KEY_ID,
            )

            await AuditLogLauncherRepository(session).record(
                action=AuditLogLauncherAction.LOGIN_SUCCESS,
                player_id=player.id,
                device_id=device.id,
                ip_address=ip,
                metadata={"discord_id": str(discord_id)},
            )

        async with self._lock:
            pending.status = "completed"
            pending.tokens = TokenPair(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=self._settings.jwt_access_ttl_seconds,
            )

    async def _exchange_and_fetch_discord_user(self, *, code: str, code_verifier: str) -> tuple[int, str | None]:
        """Troca o `code` do Discord por um token (client_secret so existe
        aqui, nunca chega no Launcher) e busca a identidade do usuario. O
        token do Discord e usado uma unica vez nesta funcao e descartado —
        nunca e persistido (regra obrigatoria do prompt)."""
        async with aiohttp.ClientSession() as http:
            token_resp = await http.post(
                f"{_DISCORD_API_BASE}/oauth2/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._settings.discord_oauth_redirect_uri,
                    "client_id": self._settings.discord_oauth_client_id,
                    "client_secret": self._settings.discord_oauth_client_secret,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_resp.status != 200:
                raise AuthError("discord_token_exchange_failed", "Discord recusou a troca de codigo.")
            token_payload = await token_resp.json()
            discord_access_token = token_payload["access_token"]

            user_resp = await http.get(
                f"{_DISCORD_API_BASE}/users/@me",
                headers={"Authorization": f"Bearer {discord_access_token}"},
            )
            if user_resp.status != 200:
                raise AuthError("discord_user_fetch_failed", "Nao foi possivel obter o perfil do Discord.")
            user_payload = await user_resp.json()
            return int(user_payload["id"]), user_payload.get("username")

    # ------------------------------------------------------------------
    # Passo 4: Launcher da poll ate completar
    # ------------------------------------------------------------------
    async def poll_device_token(self, *, device_code: str) -> PollResult:
        async with self._lock:
            self._purge_expired_locked()
            pending = self._pending_logins.get(device_code)
            if pending is None:
                return PollResult(status="expired_token")

            if pending.status == "denied":
                self._pending_logins.pop(device_code, None)
                self._state_to_device_code.pop(pending.state, None)
                return PollResult(status="access_denied")

            if pending.status == "completed":
                tokens = pending.tokens
                self._pending_logins.pop(device_code, None)
                self._state_to_device_code.pop(pending.state, None)
                return PollResult(status="success", tokens=tokens)

            now = datetime.now(UTC)
            if pending.last_poll_at is not None and (now - pending.last_poll_at).total_seconds() < _POLL_MIN_INTERVAL_SECONDS:
                return PollResult(status="slow_down", interval=_POLL_MIN_INTERVAL_SECONDS * 2)
            pending.last_poll_at = now
            return PollResult(status="authorization_pending")

    # ------------------------------------------------------------------
    # Sessoes seguintes: rotacao de refresh token
    # ------------------------------------------------------------------
    async def refresh(self, *, refresh_token: str, device_uuid: uuid.UUID, ip: str | None) -> TokenPair:
        """Nota de implementacao: erros que precisam persistir uma revogacao
        (reuso detectado, device revogado) NAO sao levantados dentro do
        `async with self._database.session()` — uma excecao ali dispara
        rollback (`database/database.py: Database.session()`), o que
        apagaria a propria revogacao que queremos gravar. Por isso o erro e
        guardado em `error_to_raise` e levantado só depois que o bloco
        termina (e comita) normalmente."""
        token_hash = hash_token(refresh_token)
        now = datetime.now(UTC)
        error_to_raise: AuthError | None = None
        result: TokenPair | None = None

        async with self._database.session() as session:
            session_repo = LauncherSessionRepository(session)
            existing = await session_repo.get_by_token_hash(token_hash)
            device = await DeviceRepository(session).get_by_id(existing.device_id) if existing else None

            if existing is None or device is None:
                error_to_raise = AuthError("invalid_refresh_token", "Refresh token invalido.")
            elif existing.revoked_at is not None:
                # Reuso de um token ja rotacionado/revogado = sinal de roubo.
                # Derruba a sessao inteira do dispositivo, nao so esse token.
                await session_repo.revoke_all_for_device(
                    device.id, reason="refresh_reuse_detected", revoked_at=now
                )
                await AuditLogLauncherRepository(session).record(
                    action=AuditLogLauncherAction.REFRESH_REUSE_DETECTED,
                    player_id=device.player_id,
                    device_id=device.id,
                    ip_address=ip,
                    metadata={"reused_session_id": str(existing.id)},
                )
                error_to_raise = AuthError(
                    "session_hijack_suspected", "Sessao revogada por reuso de refresh token."
                )
            elif existing.expires_at < now:
                error_to_raise = AuthError(
                    "refresh_token_expired", "Refresh token expirado, faca login novamente."
                )
            elif device.revoked or device.device_uuid != device_uuid:
                await session_repo.revoke_all_for_device(device.id, reason="device_mismatch", revoked_at=now)
                await AuditLogLauncherRepository(session).record(
                    action=AuditLogLauncherAction.DEVICE_REVOKED,
                    player_id=device.player_id,
                    device_id=device.id,
                    ip_address=ip,
                    metadata={"reason": "device_mismatch_or_revoked"},
                )
                error_to_raise = AuthError("device_revoked", "Dispositivo revogado.")
            else:
                existing.revoked_at = now
                existing.revoked_reason = "rotated"

                new_refresh_token = generate_refresh_token()
                new_session = LauncherSession(
                    device_id=device.id,
                    refresh_token_hash=hash_token(new_refresh_token),
                    jwt_key_id=_JWT_KEY_ID,
                    issued_at=now,
                    expires_at=now + timedelta(days=self._settings.refresh_token_ttl_days),
                    last_used_at=now,
                    last_ip=ip,
                )
                await session_repo.add(new_session)
                await session.flush()

                device.last_seen_at = now
                device.last_ip = ip

                access_token = jwt_service.encode_access_token(
                    player_id=device.player_id,
                    device_id=device.id,
                    session_id=new_session.id,
                    secret_key=self._settings.jwt_secret_key,
                    ttl_seconds=self._settings.jwt_access_ttl_seconds,
                    key_id=_JWT_KEY_ID,
                )

                await AuditLogLauncherRepository(session).record(
                    action=AuditLogLauncherAction.REFRESH_ROTATED,
                    player_id=device.player_id,
                    device_id=device.id,
                    ip_address=ip,
                    metadata={"old_session_id": str(existing.id), "new_session_id": str(new_session.id)},
                )

                result = TokenPair(
                    access_token=access_token,
                    refresh_token=new_refresh_token,
                    expires_in=self._settings.jwt_access_ttl_seconds,
                )

        if error_to_raise is not None:
            raise error_to_raise
        assert result is not None
        return result

    # ------------------------------------------------------------------
    # Logout
    # ------------------------------------------------------------------
    async def logout(self, *, refresh_token: str, ip: str | None) -> None:
        token_hash = hash_token(refresh_token)
        now = datetime.now(UTC)
        async with self._database.session() as session:
            session_repo = LauncherSessionRepository(session)
            existing = await session_repo.get_by_token_hash(token_hash)
            if existing is None or existing.revoked_at is not None:
                return  # idempotente — nao vaza se o token existia ou nao
            existing.revoked_at = now
            existing.revoked_reason = "logout"

            device = await DeviceRepository(session).get_by_id(existing.device_id)
            await AuditLogLauncherRepository(session).record(
                action=AuditLogLauncherAction.LOGOUT,
                player_id=device.player_id if device else None,
                device_id=existing.device_id,
                ip_address=ip,
            )

    async def logout_all(self, *, player_id: uuid.UUID, ip: str | None) -> int:
        now = datetime.now(UTC)
        revoked_count = 0
        async with self._database.session() as session:
            device_repo = DeviceRepository(session)
            session_repo = LauncherSessionRepository(session)
            devices = await device_repo.list_active_by_player(player_id)
            for device in devices:
                active_sessions = await session_repo.list_active_by_device(device.id)
                revoked_count += len(active_sessions)
                await session_repo.revoke_all_for_device(device.id, reason="logout_all", revoked_at=now)

            await AuditLogLauncherRepository(session).record(
                action=AuditLogLauncherAction.LOGOUT_ALL,
                player_id=player_id,
                ip_address=ip,
                metadata={"sessions_revoked": revoked_count},
            )
        return revoked_count

    # ------------------------------------------------------------------
    # Validacao de access token (usado pelo dependency de rota protegida)
    # ------------------------------------------------------------------
    async def get_player_from_access_token(self, token: str):
        """Alem de validar assinatura/expiracao do JWT, confere que a
        LauncherSession referenciada (`sid`) ainda esta viva — sem isso, um
        access_token roubado continuaria valido ate expirar sozinho (ate
        `jwt_access_ttl_seconds`) mesmo depois de logout/logout_all/device
        revogado/reuso de refresh detectado, porque o JWT em si e stateless
        e nao sabe que a sessao foi revogada por fora. Esta checagem fecha
        essa janela: revogar a sessao agora invalida o access_token na
        proxima requisicao, nao so no proximo refresh."""
        try:
            claims = jwt_service.decode_access_token(token, secret_key=self._settings.jwt_secret_key)
        except jwt_service.JWTError as exc:
            raise AuthError("invalid_token", str(exc))

        async with self._database.session() as session:
            player = await PlayerRepository(session).get_by_id(claims.player_id)
            if player is None:
                raise AuthError("invalid_token", "Player nao encontrado.")
            if player.is_banned:
                raise AuthError("player_banned", "Conta banida.")

            launcher_session = await LauncherSessionRepository(session).get_by_id(claims.session_id)
            if launcher_session is None or launcher_session.revoked_at is not None:
                raise AuthError("invalid_token", "Sessao revogada.")
            if launcher_session.device_id != claims.device_id:
                raise AuthError("invalid_token", "Token nao corresponde ao dispositivo da sessao.")

            return player
