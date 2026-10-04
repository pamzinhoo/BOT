from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from cogs.redemption import RedemptionCog
from views.redemption_view import RedemptionModal, redemption_only_view
from views.shop_view import ShopPanelView


def _interaction(*, code: str, result: dict | None = None) -> tuple[RedemptionModal, MagicMock]:
    modal = RedemptionModal()
    modal.code._value = code
    member = MagicMock(spec=discord.Member)
    member.send = AsyncMock()
    guild = SimpleNamespace(id=123)
    member.guild = guild
    service = SimpleNamespace(
        redeem=AsyncMock(return_value=result),
        claim_notification=AsyncMock(return_value=True),
        complete_notification=AsyncMock(),
    )
    interaction = MagicMock()
    interaction.guild = guild
    interaction.guild_id = guild.id
    interaction.user = member
    interaction.client.redemption_service = service
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return modal, interaction


def test_shop_panel_keeps_persistent_redemption_button() -> None:
    view = ShopPanelView()
    assert view.is_persistent()
    assert any(item.custom_id == "limerence:shop:redeem" for item in view.children)
    assert len(redemption_only_view().children) == 1


async def test_invalid_code_never_calls_service() -> None:
    for code in ("ABCDEFGH", "ıBCD1234"):
        modal, interaction = _interaction(code=code)
        await modal.on_submit(interaction)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.client.redemption_service.redeem.assert_not_awaited()
        assert "8 caracteres" in interaction.followup.send.call_args.args[0]


async def test_cross_guild_member_never_calls_service() -> None:
    modal, interaction = _interaction(code="ABCD1234")
    interaction.user.guild = SimpleNamespace(id=999)
    await modal.on_submit(interaction)
    interaction.client.redemption_service.redeem.assert_not_awaited()
    assert "somente no servidor" in interaction.followup.send.call_args.args[0]


async def test_pending_and_failed_status_never_claim_reward() -> None:
    for status in ("pending", "failed"):
        modal, interaction = _interaction(
            code="ABCD1234",
            result={
                "id": str(uuid.uuid4()),
                "status": status,
                "message": "Estado privado",
                "delivery": "dm",
                "notification_status": "pending",
            },
        )
        await modal.on_submit(interaction)
        service = interaction.client.redemption_service
        service.claim_notification.assert_not_awaited()
        interaction.user.send.assert_not_awaited()
        assert "Estado privado" in interaction.followup.send.call_args.args[0]
        assert interaction.followup.send.call_args.args == ("Estado privado",)
        assert interaction.followup.send.call_args.kwargs["ephemeral"] is True
        assert interaction.followup.send.call_args.kwargs["allowed_mentions"].everyone is False


async def test_successful_channel_delivery_claims_and_marks_sent() -> None:
    redemption_id = uuid.uuid4()
    modal, interaction = _interaction(
        code="abcd1234",
        result={
            "id": str(redemption_id),
            "status": "delivered",
            "message": "Seu prêmio privado",
            "delivery": "channel",
            "notification_status": "pending",
        },
    )
    await modal.on_submit(interaction)
    service = interaction.client.redemption_service
    service.redeem.assert_awaited_once_with(interaction.guild, interaction.user, "ABCD1234")
    service.claim_notification.assert_awaited_once_with(123, redemption_id)
    interaction.followup.send.assert_awaited_once()
    assert interaction.followup.send.call_args.args == ("Seu prêmio privado",)
    assert interaction.followup.send.call_args.kwargs["ephemeral"] is True
    assert interaction.followup.send.call_args.kwargs["allowed_mentions"].everyone is False
    assert interaction.followup.send.call_args.kwargs["allowed_mentions"].roles is False
    assert interaction.followup.send.call_args.kwargs["allowed_mentions"].users is False
    service.complete_notification.assert_awaited_once_with(123, redemption_id, "sent")


async def test_dm_forbidden_uses_ephemeral_fallback_without_new_claim() -> None:
    redemption_id = uuid.uuid4()
    modal, interaction = _interaction(
        code="ABCD1234",
        result={
            "id": str(redemption_id),
            "status": "delivered",
            "message": "Seu prêmio privado",
            "delivery": "dm",
            "notification_status": "pending",
        },
    )
    interaction.user.send.side_effect = discord.Forbidden(
        MagicMock(status=403, reason="Forbidden"), "DMs desabilitadas"
    )
    await modal.on_submit(interaction)
    service = interaction.client.redemption_service
    service.claim_notification.assert_awaited_once()
    interaction.followup.send.assert_awaited_once()
    assert interaction.followup.send.call_args.args == ("Seu prêmio privado",)
    assert interaction.followup.send.call_args.kwargs["ephemeral"] is True
    assert interaction.followup.send.call_args.kwargs["allowed_mentions"].everyone is False
    assert interaction.followup.send.call_args.kwargs["allowed_mentions"].roles is False
    assert interaction.followup.send.call_args.kwargs["allowed_mentions"].users is False
    service.complete_notification.assert_awaited_once_with(123, redemption_id, "sent")


async def test_dm_timeout_marks_delivery_uncertain_without_revealing_reward() -> None:
    redemption_id = uuid.uuid4()
    modal, interaction = _interaction(
        code="ABCD1234",
        result={
            "id": str(redemption_id),
            "status": "delivered",
            "message": "Segredo",
            "delivery": "dm",
            "notification_status": "pending",
        },
    )
    interaction.user.send.side_effect = TimeoutError()
    await modal.on_submit(interaction)
    interaction.client.redemption_service.complete_notification.assert_awaited_once_with(
        123, redemption_id, "uncertain"
    )
    assert "Segredo" not in interaction.followup.send.call_args.args[0]


async def test_claim_failure_does_not_send_reward_again() -> None:
    modal, interaction = _interaction(
        code="ABCD1234",
        result={
            "id": str(uuid.uuid4()),
            "status": "delivered",
            "message": "Segredo",
            "delivery": "dm",
            "notification_status": "sent",
        },
    )
    interaction.client.redemption_service.claim_notification.return_value = False
    await modal.on_submit(interaction)
    interaction.user.send.assert_not_awaited()
    interaction.client.redemption_service.complete_notification.assert_not_awaited()
    assert "Segredo" not in interaction.followup.send.call_args.args[0]


async def test_scheduler_continues_after_service_error() -> None:
    service = SimpleNamespace(
        process_pending=AsyncMock(side_effect=[RuntimeError("offline"), None])
    )
    cog = SimpleNamespace(bot=SimpleNamespace(redemption_service=service))
    await RedemptionCog.process_redemptions.coro(cog)
    await RedemptionCog.process_redemptions.coro(cog)
    assert service.process_pending.await_count == 2


async def test_startup_refreshes_each_existing_shop_panel_even_after_error() -> None:
    refresh = AsyncMock(side_effect=[RuntimeError("missing permissions"), None])
    bot = SimpleNamespace(
        wait_until_ready=AsyncMock(),
        guilds=[SimpleNamespace(id=1), SimpleNamespace(id=2)],
        painel_service=SimpleNamespace(refresh_shop_panel=refresh),
    )
    await RedemptionCog.before_process_redemptions(SimpleNamespace(bot=bot))
    bot.wait_until_ready.assert_awaited_once()
    assert [call.args[0] for call in refresh.await_args_list] == [1, 2]
