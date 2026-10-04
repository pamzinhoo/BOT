from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from core.rate_limiter import RateLimitExceeded
from services.redemption_service import RedemptionError, RedemptionService, normalize_code
from views.embeds import audit_log_embed


@pytest.mark.parametrize(
    "value", ["ABCDEFGH", "12345678", "ABCD123", "ABCD12345", "ÁBCD1234", "ＡBCD1234"]
)
def test_code_rejects_missing_mix_wrong_length_and_unicode(value: str) -> None:
    with pytest.raises(RedemptionError):
        normalize_code(value)


def test_code_normalizes_ascii_case() -> None:
    assert normalize_code(" abcd1234 ") == "ABCD1234"


def test_config_validation_prevents_unsafe_role_and_delivery_settings() -> None:
    valid = RedemptionService._validate(
        {
            "code": "abcd1234",
            "reward_type": "role",
            "role_id": 123,
            "role_duration_seconds": 60,
            "temporary_role_ack": True,
            "delivery": "dm",
            "message": "{usuario}: pronto",
        }
    )
    assert valid["code"] == "ABCD1234"
    assert valid["role_duration_seconds"] == 60
    for change in (
        {"temporary_role_ack": False},
        {"role_id": True},
        {"delivery": "public"},
        {"message": "x" * 1801},
        {"starts_at": datetime.now(UTC) + timedelta(days=1), "expires_at": datetime.now(UTC)},
    ):
        with pytest.raises(RedemptionError):
            RedemptionService._validate({**valid, **change})


async def test_role_validation_allows_shared_roles_but_blocks_admin_and_unmanageable_roles() -> (
    None
):
    service = RedemptionService(MagicMock())
    service._shared_role = AsyncMock(return_value=False)
    role = MagicMock()
    role.id = 123
    role.managed = False
    role.__ge__.return_value = False
    role.permissions = discord.Permissions.none()
    guild = MagicMock()
    guild.id = 9
    guild.get_role.return_value = role
    guild.me.guild_permissions.manage_roles = True
    guild.me.guild_permissions.view_audit_log = True
    assert await service.validate_role(guild, 123, temporary=True) is role

    role.permissions.administrator = True
    with pytest.raises(RedemptionError, match="administrativas"):
        await service.validate_role(guild, 123)
    role.permissions.administrator = False
    service._shared_role.return_value = True
    assert await service.validate_role(guild, 123) is role
    assert await service.validate_role(guild, 123, temporary=True) is role
    service._shared_role.return_value = False
    role.__ge__.return_value = True
    with pytest.raises(RedemptionError, match="acima"):
        await service.validate_role(guild, 123)


async def test_rate_limit_rejects_before_database_or_reservation() -> None:
    database = MagicMock()
    service = RedemptionService(database)
    service._users.hit = AsyncMock(side_effect=RateLimitExceeded(30))
    guild = SimpleNamespace(id=9)
    member = SimpleNamespace(id=7, guild=guild, bot=False)
    with pytest.raises(RedemptionError, match="Muitas tentativas"):
        await service.redeem(guild, member, "ABCD1234")
    database.session.assert_not_called()


def test_pending_result_never_exposes_reward_snapshot() -> None:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        guild_id=9,
        user_id=7,
        status="pending",
        message="Segredo",
        delivery="dm",
        notification_status="pending",
    )
    assert "Segredo" not in RedemptionService._result(row)["message"]
    row.status = "failed"
    assert "Segredo" not in RedemptionService._result(row)["message"]
    row.status = "uncertain"
    assert "Segredo" not in RedemptionService._result(row)["message"]
    row.status = "delivered"
    assert RedemptionService._result(row)["message"] == "Segredo"


async def test_notification_claim_requires_successful_atomic_update() -> None:
    result = MagicMock()
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    database = MagicMock()

    @asynccontextmanager
    async def transaction():
        yield session

    database.session.side_effect = transaction
    service = RedemptionService(database)
    redemption_id = uuid.uuid4()
    result.scalar_one_or_none.return_value = None
    assert await service.claim_notification(9, redemption_id) is False
    result.scalar_one_or_none.return_value = redemption_id
    assert await service.claim_notification(9, redemption_id) is True


@pytest.mark.parametrize("name", ["Jogador de teste", None])
async def test_discord_redemption_log_identifies_recipient_without_network_lookup(name) -> None:
    user_id = 1234567890123456789
    member = SimpleNamespace(display_name=name) if name else None
    guild = SimpleNamespace(
        id=9, get_member=lambda member_id: member if member_id == user_id else None
    )
    record = AsyncMock()
    bot = SimpleNamespace(
        get_guild=lambda guild_id: guild, audit_log_service=SimpleNamespace(record=record)
    )
    database = MagicMock()
    service = RedemptionService(database, bot)
    row = SimpleNamespace(id=uuid.uuid4(), guild_id=guild.id, user_id=user_id)
    service._claim_delivery = AsyncMock(return_value=(row, None))

    await service._deliver(guild, row.id)

    payload = record.await_args.kwargs
    assert payload["target_id"] == user_id
    assert str(user_id) in payload["target_name"]
    if name:
        assert name in payload["target_name"]
    embed = audit_log_embed(
        payload["category"],
        payload["action"],
        executor_id=None,
        executor_name=None,
        target_id=payload["target_id"],
        target_name=payload["target_name"],
        reason=None,
        details=payload["details"],
    )
    target = next(field.value for field in embed.fields if field.name == "Alvo")
    assert str(user_id) in target
    details = next(field.value for field in embed.fields if field.name == "Detalhes")
    assert str(user_id) in details
    if name:
        assert name in details
    database.session.assert_not_called()
