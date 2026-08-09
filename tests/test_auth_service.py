from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from core.security.tokens import hash_token
from database.models.audit_log_launcher import AuditLogLauncherAction
from database.models.device import Device
from database.models.launcher_session import LauncherSession
from database.models.player import Player
from services.auth_service import AuthError, AuthService
from tests._fakes_auth import AuthFakeStore, FakeDatabase, install_fake_repositories


@pytest.fixture
def store() -> AuthFakeStore:
    return AuthFakeStore()


@pytest.fixture
def auth_service(monkeypatch, store: AuthFakeStore, valid_env) -> AuthService:
    from config.settings import get_settings

    install_fake_repositories(monkeypatch, store)
    return AuthService(FakeDatabase(store), get_settings())


def _seed_player_device_session(store: AuthFakeStore, *, refresh_token: str) -> tuple[Player, Device, LauncherSession]:
    now = datetime.now(UTC)
    player = Player(discord_id=555, discord_username="tester", linked_at=now)
    player.id = uuid.uuid4()
    player.is_banned = False
    store.players[player.id] = player

    device = Device(
        player_id=player.id,
        device_uuid=uuid.uuid4(),
        first_seen_at=now,
        last_seen_at=now,
        revoked=False,
    )
    device.id = uuid.uuid4()
    store.devices[device.id] = device

    session_row = LauncherSession(
        device_id=device.id,
        refresh_token_hash=hash_token(refresh_token),
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    session_row.id = uuid.uuid4()
    store.sessions[session_row.id] = session_row

    return player, device, session_row


# --- device code / poll ----------------------------------------------------


async def test_create_device_login_then_poll_is_pending(auth_service: AuthService) -> None:
    issued = await auth_service.create_device_login(
        device_uuid=uuid.uuid4(), os_info="Windows 11", launcher_version="0.1.0"
    )
    assert issued.device_code
    assert len(issued.user_code) == 9  # XXXX-XXXX

    result = await auth_service.poll_device_token(device_code=issued.device_code)
    assert result.status == "authorization_pending"


async def test_poll_unknown_device_code_is_expired(auth_service: AuthService) -> None:
    result = await auth_service.poll_device_token(device_code="does-not-exist")
    assert result.status == "expired_token"


async def test_poll_too_soon_returns_slow_down(auth_service: AuthService) -> None:
    issued = await auth_service.create_device_login(device_uuid=uuid.uuid4(), os_info=None, launcher_version=None)
    first = await auth_service.poll_device_token(device_code=issued.device_code)
    second = await auth_service.poll_device_token(device_code=issued.device_code)
    assert first.status == "authorization_pending"
    assert second.status == "slow_down"


async def test_build_authorize_url_rejects_invalid_user_code(auth_service: AuthService) -> None:
    with pytest.raises(AuthError) as exc_info:
        await auth_service.build_discord_authorize_url(user_code="ZZZZ-ZZZZ")
    assert exc_info.value.code == "invalid_user_code"


async def test_build_authorize_url_contains_pkce_and_state(auth_service: AuthService) -> None:
    issued = await auth_service.create_device_login(device_uuid=uuid.uuid4(), os_info=None, launcher_version=None)
    url = await auth_service.build_discord_authorize_url(user_code=issued.user_code)
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    assert "state=" in url
    assert "client_secret" not in url  # PKCE nao expoe secret nenhum


# --- discord callback --------------------------------------------------------


async def test_discord_callback_creates_player_device_session(
    auth_service: AuthService, store: AuthFakeStore, monkeypatch
) -> None:
    issued = await auth_service.create_device_login(
        device_uuid=uuid.uuid4(), os_info="Windows 11", launcher_version="0.1.0"
    )

    async def fake_exchange(self, *, code, code_verifier):
        assert code == "the-code"
        return 999888777, "playerone"

    monkeypatch.setattr(AuthService, "_exchange_and_fetch_discord_user", fake_exchange)

    pending = auth_service._pending_logins[issued.device_code]
    await auth_service.handle_discord_callback(code="the-code", state=pending.state, ip="1.2.3.4")

    assert len(store.players) == 1
    assert len(store.devices) == 1
    assert len(store.sessions) == 1
    assert any(a["action"] == AuditLogLauncherAction.LOGIN_SUCCESS for a in store.audit_logs)

    poll_result = await auth_service.poll_device_token(device_code=issued.device_code)
    assert poll_result.status == "success"
    assert poll_result.tokens is not None
    assert poll_result.tokens.access_token
    assert poll_result.tokens.refresh_token

    # device_code e de uso unico — segunda tentativa nao acha mais nada.
    second_poll = await auth_service.poll_device_token(device_code=issued.device_code)
    assert second_poll.status == "expired_token"


async def test_discord_callback_rejects_unknown_state(auth_service: AuthService) -> None:
    with pytest.raises(AuthError) as exc_info:
        await auth_service.handle_discord_callback(code="x", state="bogus-state", ip=None)
    assert exc_info.value.code == "invalid_state"


async def test_discord_callback_marks_failed_on_exchange_error(
    auth_service: AuthService, store: AuthFakeStore, monkeypatch
) -> None:
    issued = await auth_service.create_device_login(device_uuid=uuid.uuid4(), os_info=None, launcher_version=None)

    async def failing_exchange(self, *, code, code_verifier):
        raise RuntimeError("discord fora do ar")

    monkeypatch.setattr(AuthService, "_exchange_and_fetch_discord_user", failing_exchange)

    pending = auth_service._pending_logins[issued.device_code]
    with pytest.raises(AuthError) as exc_info:
        await auth_service.handle_discord_callback(code="x", state=pending.state, ip=None)
    assert exc_info.value.code == "discord_exchange_failed"

    poll_result = await auth_service.poll_device_token(device_code=issued.device_code)
    assert poll_result.status == "access_denied"
    assert any(a["action"] == AuditLogLauncherAction.LOGIN_FAILED for a in store.audit_logs)


# --- refresh / rotacao / hijacking -----------------------------------------


async def test_refresh_rejects_unknown_token(auth_service: AuthService) -> None:
    with pytest.raises(AuthError) as exc_info:
        await auth_service.refresh(refresh_token="bogus", device_uuid=uuid.uuid4(), ip=None)
    assert exc_info.value.code == "invalid_refresh_token"


async def test_refresh_rotates_token_and_revokes_old(auth_service: AuthService, store: AuthFakeStore) -> None:
    refresh_token = "the-refresh-token"
    player, device, session_row = _seed_player_device_session(store, refresh_token=refresh_token)

    new_tokens = await auth_service.refresh(refresh_token=refresh_token, device_uuid=device.device_uuid, ip="9.9.9.9")

    assert new_tokens.refresh_token != refresh_token
    assert session_row.revoked_at is not None
    assert session_row.revoked_reason == "rotated"
    assert len(store.sessions) == 2
    assert any(a["action"] == AuditLogLauncherAction.REFRESH_ROTATED for a in store.audit_logs)


async def test_refresh_reuse_of_revoked_token_revokes_whole_device(
    auth_service: AuthService, store: AuthFakeStore
) -> None:
    refresh_token = "stolen-token"
    player, device, session_row = _seed_player_device_session(store, refresh_token=refresh_token)
    session_row.revoked_at = datetime.now(UTC)
    session_row.revoked_reason = "rotated"

    # uma segunda sessao ativa no mesmo device, pra provar que a cascata mata tudo
    other_session = LauncherSession(
        device_id=device.id,
        refresh_token_hash=hash_token("other-token"),
        issued_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    other_session.id = uuid.uuid4()
    store.sessions[other_session.id] = other_session

    with pytest.raises(AuthError) as exc_info:
        await auth_service.refresh(refresh_token=refresh_token, device_uuid=device.device_uuid, ip="1.1.1.1")

    assert exc_info.value.code == "session_hijack_suspected"
    assert other_session.revoked_at is not None
    assert other_session.revoked_reason == "refresh_reuse_detected"
    assert any(a["action"] == AuditLogLauncherAction.REFRESH_REUSE_DETECTED for a in store.audit_logs)


async def test_refresh_rejects_wrong_device_uuid(auth_service: AuthService, store: AuthFakeStore) -> None:
    refresh_token = "the-refresh-token"
    player, device, session_row = _seed_player_device_session(store, refresh_token=refresh_token)

    with pytest.raises(AuthError) as exc_info:
        await auth_service.refresh(refresh_token=refresh_token, device_uuid=uuid.uuid4(), ip=None)

    assert exc_info.value.code == "device_revoked"
    assert session_row.revoked_at is not None  # cascata revogou mesmo com erro


async def test_refresh_rejects_expired_token(auth_service: AuthService, store: AuthFakeStore) -> None:
    refresh_token = "expired-token"
    player, device, session_row = _seed_player_device_session(store, refresh_token=refresh_token)
    session_row.expires_at = datetime.now(UTC) - timedelta(days=1)

    with pytest.raises(AuthError) as exc_info:
        await auth_service.refresh(refresh_token=refresh_token, device_uuid=device.device_uuid, ip=None)
    assert exc_info.value.code == "refresh_token_expired"


# --- logout ------------------------------------------------------------------


async def test_logout_unknown_token_is_noop(auth_service: AuthService) -> None:
    await auth_service.logout(refresh_token="bogus", ip=None)  # nao levanta, e idempotente


async def test_logout_revokes_matching_session(auth_service: AuthService, store: AuthFakeStore) -> None:
    refresh_token = "logout-me"
    player, device, session_row = _seed_player_device_session(store, refresh_token=refresh_token)

    await auth_service.logout(refresh_token=refresh_token, ip="2.2.2.2")

    assert session_row.revoked_at is not None
    assert session_row.revoked_reason == "logout"
    assert any(a["action"] == AuditLogLauncherAction.LOGOUT for a in store.audit_logs)


async def test_logout_all_revokes_every_active_session_of_player(
    auth_service: AuthService, store: AuthFakeStore
) -> None:
    player, device, session_row = _seed_player_device_session(store, refresh_token="tok-1")
    other_session = LauncherSession(
        device_id=device.id,
        refresh_token_hash=hash_token("tok-2"),
        issued_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    other_session.id = uuid.uuid4()
    store.sessions[other_session.id] = other_session

    revoked_count = await auth_service.logout_all(player_id=player.id, ip=None)

    assert revoked_count == 2
    assert session_row.revoked_at is not None
    assert other_session.revoked_at is not None
    assert any(a["action"] == AuditLogLauncherAction.LOGOUT_ALL for a in store.audit_logs)


# --- validacao de access token -----------------------------------------------


async def test_get_player_from_access_token_roundtrip(auth_service: AuthService, store: AuthFakeStore) -> None:
    from core.security import jwt_service

    player, device, session_row = _seed_player_device_session(store, refresh_token="whatever")
    token = jwt_service.encode_access_token(
        player_id=player.id,
        device_id=device.id,
        session_id=session_row.id,
        secret_key=auth_service._settings.jwt_secret_key,
        ttl_seconds=900,
    )

    resolved = await auth_service.get_player_from_access_token(token)
    assert resolved.id == player.id


async def test_get_player_from_access_token_rejects_bad_signature(auth_service: AuthService) -> None:
    with pytest.raises(AuthError) as exc_info:
        await auth_service.get_player_from_access_token("not-a-real-jwt")
    assert exc_info.value.code == "invalid_token"


async def test_get_player_from_access_token_rejects_banned_player(
    auth_service: AuthService, store: AuthFakeStore
) -> None:
    from core.security import jwt_service

    player, device, session_row = _seed_player_device_session(store, refresh_token="whatever")
    player.is_banned = True
    token = jwt_service.encode_access_token(
        player_id=player.id,
        device_id=device.id,
        session_id=session_row.id,
        secret_key=auth_service._settings.jwt_secret_key,
        ttl_seconds=900,
    )

    with pytest.raises(AuthError) as exc_info:
        await auth_service.get_player_from_access_token(token)
    assert exc_info.value.code == "player_banned"


async def test_get_player_from_access_token_rejects_revoked_session(
    auth_service: AuthService, store: AuthFakeStore
) -> None:
    """Regressao Fase 6: access_token continua com assinatura/exp validos,
    mas a sessao (`sid`) foi revogada (logout) — precisa ser rejeitado
    imediatamente, sem esperar o token expirar sozinho."""
    from core.security import jwt_service

    player, device, session_row = _seed_player_device_session(store, refresh_token="whatever")
    token = jwt_service.encode_access_token(
        player_id=player.id, device_id=device.id, session_id=session_row.id,
        secret_key=auth_service._settings.jwt_secret_key, ttl_seconds=900,
    )
    await auth_service.logout(refresh_token="whatever", ip=None)

    with pytest.raises(AuthError) as exc_info:
        await auth_service.get_player_from_access_token(token)
    assert exc_info.value.code == "invalid_token"


async def test_get_player_from_access_token_rejects_device_revoked_via_cascade(
    auth_service: AuthService, store: AuthFakeStore
) -> None:
    """logout_all/device revocation passam por revoke_all_for_device — o
    access_token emitido antes tem que morrer junto, mesmo sem logout
    individual daquela sessao especifica."""
    from core.security import jwt_service

    player, device, session_row = _seed_player_device_session(store, refresh_token="whatever")
    token = jwt_service.encode_access_token(
        player_id=player.id, device_id=device.id, session_id=session_row.id,
        secret_key=auth_service._settings.jwt_secret_key, ttl_seconds=900,
    )
    await auth_service.logout_all(player_id=player.id, ip=None)

    with pytest.raises(AuthError) as exc_info:
        await auth_service.get_player_from_access_token(token)
    assert exc_info.value.code == "invalid_token"


async def test_get_player_from_access_token_rejects_unknown_session(auth_service: AuthService, store: AuthFakeStore) -> None:
    import uuid

    from core.security import jwt_service

    player, device, _session_row = _seed_player_device_session(store, refresh_token="whatever")
    token = jwt_service.encode_access_token(
        player_id=player.id, device_id=device.id, session_id=uuid.uuid4(),
        secret_key=auth_service._settings.jwt_secret_key, ttl_seconds=900,
    )

    with pytest.raises(AuthError) as exc_info:
        await auth_service.get_player_from_access_token(token)
    assert exc_info.value.code == "invalid_token"
