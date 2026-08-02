from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import discord

from database.models.plan import Plan
from database.models.subscription_renewal import SubscriptionMessageType
from services.plan_service import render_placeholders
from services.subscription_reminder_service import days_left_until
from services.subscription_renewal_config_service import DEFAULT_MESSAGES


def _fake_member() -> discord.Member:
    member = MagicMock(spec=discord.Member)
    member.mention = "<@123>"
    return member


def _fake_guild() -> discord.Guild:
    guild = MagicMock(spec=discord.Guild)
    guild.name = "Servidor Teste"
    guild.member_count = 42
    return guild


def _plan() -> Plan:
    return Plan(guild_id=1, name="VIP", emoji="💎", price_monthly=1990, currency="BRL")


def test_renewal_placeholders_are_rendered() -> None:
    result = render_placeholders(
        "{mention} {plan_emoji} {plan_name} vence em {days_left} dias ({expires_at}), "
        "carência {grace_days}, loja {store_command}, id {subscription_id}",
        member=_fake_member(),
        guild=_fake_guild(),
        plan=_plan(),
        expires_at=datetime(2026, 8, 10, tzinfo=UTC),
        days_left=3,
        grace_days=5,
        subscription_id="abc",
    )

    assert result == (
        "<@123> 💎 VIP vence em 3 dias (10/08/2026), carência 5, loja /loja, id abc"
    )


def test_user_placeholder_keeps_mention_behaviour() -> None:
    """{user} nunca pode mudar de significado — mensagens de Plano/Booster já
    cadastradas dependem dele ser a menção."""
    result = render_placeholders("{user} == {mention}", member=_fake_member())

    assert result == "<@123> == <@123>"


def test_unknown_renewal_placeholders_fall_back() -> None:
    result = render_placeholders("{days_left} {grace_days} {expires_at} {renew_link}")

    assert result == "— — — —"


def test_days_left_rounds_up_so_a_daily_cycle_never_skips_a_reminder() -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)

    # faltando 6 dias e 23h ainda conta como "7 dias antes"
    assert days_left_until(now + timedelta(days=6, hours=23), now) == 7
    assert days_left_until(now + timedelta(days=1), now) == 1
    assert days_left_until(now + timedelta(hours=1), now) == 1
    assert days_left_until(now - timedelta(hours=1), now) == 0


def test_every_message_type_has_an_editable_default() -> None:
    assert set(DEFAULT_MESSAGES) == set(SubscriptionMessageType)
    for message_type, text in DEFAULT_MESSAGES.items():
        assert text.strip(), message_type


def test_reminder_ledger_key_is_period_scoped() -> None:
    """Sanidade do contrato de idempotência: a chave é
    (subscription_id, reminder_type, period_end) — renovar move o período e
    libera o mesmo aviso pro ciclo seguinte, sem repetir no ciclo atual."""
    from database.models.subscription_renewal import SubscriptionReminder

    constraint = next(
        c for c in SubscriptionReminder.__table__.constraints if c.name == "uq_subscription_reminder_once"
    )
    assert {c.name for c in constraint.columns} == {
        "subscription_id",
        "reminder_type",
        "period_end",
    }
    assert isinstance(uuid.uuid4(), uuid.UUID)
