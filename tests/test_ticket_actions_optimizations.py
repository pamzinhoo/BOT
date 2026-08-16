from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import discord

from database.models.ticket import Ticket, TicketCategory, TicketStatus
from database.models.ticket_panel import TicketPanel
from services.claim_service import ClaimError
from views.ticket_actions_view import TicketActionsView, _IncludeUserSelect, _RemoveUserSelect


def _ticket(*, claimed_by: uuid.UUID | None = None, status: TicketStatus = TicketStatus.OPEN) -> Ticket:
    ticket = Ticket(
        guild_id=1,
        channel_id=999,
        opened_by_discord_id=42,
        category=TicketCategory.OUTRO,
        status=status,
        claimed_by_staff_id=claimed_by,
        created_at=datetime.now(UTC),
    )
    ticket.id = uuid.uuid4()
    return ticket


def _panel() -> TicketPanel:
    panel = TicketPanel(guild_id=1, key="suporte", name="Suporte")
    panel.id = uuid.uuid4()
    panel.claim_role_ids = []
    return panel


def _admin_member() -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.guild_permissions.administrator = True
    member.display_name = "Staffer"
    member.mention = "<@777>"
    member.id = 777
    return member


def _interaction_for_component(*, bot: MagicMock, member: MagicMock, channel_id: int = 999) -> MagicMock:
    interaction = MagicMock()
    interaction.client = bot
    interaction.user = member
    interaction.channel_id = channel_id
    interaction.guild = MagicMock()
    interaction.guild.id = 1
    interaction.guild.get_member = MagicMock(return_value=MagicMock(spec=discord.Member, mention="<@42>", display_name="Pam"))
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    message = MagicMock(spec=discord.Message)
    message.edit = AsyncMock()
    interaction.message = message
    return interaction


def _staff() -> MagicMock:
    staff = MagicMock()
    staff.id = uuid.uuid4()
    staff.display_name = "Staffer"
    return staff


# ============================ claim(): get_panel_for_ticket ==============================


async def test_claim_calls_get_panel_for_ticket_only_once() -> None:
    """Problema 1 do benchmark: claim() chamava get_panel_for_ticket() 2x na
    mesma interacao (checagem de claim_role_ids + reconstrucao do embed do
    painel). Agora o resultado da 1a chamada e reutilizado — so 1 round-trip."""
    bot = MagicMock()
    panel = _panel()
    ticket = _ticket()
    claimed_ticket = _ticket(claimed_by=uuid.uuid4(), status=TicketStatus.CLAIMED)

    bot.ticket_service.get_by_channel_id = AsyncMock(side_effect=[ticket, claimed_ticket])
    bot.ticket_panel_service.get_panel_for_ticket = AsyncMock(return_value=panel)
    bot.staff_service.ensure_staff = AsyncMock(return_value=_staff())
    bot.claim_service.claim_ticket = AsyncMock(return_value=MagicMock())
    bot.log_service.record_background = MagicMock()
    bot.painel_service.refresh_dashboard = AsyncMock()

    member = _admin_member()
    interaction = _interaction_for_component(bot=bot, member=member)

    view = TicketActionsView()
    await view.claim.callback(interaction)

    assert bot.ticket_panel_service.get_panel_for_ticket.await_count == 1
    bot.claim_service.claim_ticket.assert_awaited_once()
    interaction.followup.send.assert_awaited()
    interaction.message.edit.assert_awaited_once()


async def test_claim_still_works_and_refreshes_panel_message() -> None:
    bot = MagicMock()
    ticket = _ticket()
    claimed_ticket = _ticket(claimed_by=uuid.uuid4(), status=TicketStatus.CLAIMED)
    bot.ticket_service.get_by_channel_id = AsyncMock(side_effect=[ticket, claimed_ticket])
    bot.ticket_panel_service.get_panel_for_ticket = AsyncMock(return_value=None)
    bot.staff_service.ensure_staff = AsyncMock(return_value=_staff())
    bot.claim_service.claim_ticket = AsyncMock(return_value=MagicMock())
    bot.log_service.record_background = MagicMock()
    bot.painel_service.refresh_dashboard = AsyncMock()

    member = _admin_member()
    interaction = _interaction_for_component(bot=bot, member=member)

    view = TicketActionsView()
    await view.claim.callback(interaction)

    interaction.response.defer.assert_awaited_once()
    bot.log_service.record_background.assert_called_once()
    interaction.message.edit.assert_awaited_once()
    interaction.followup.send.assert_awaited()


async def test_claim_still_rejects_already_claimed_ticket_without_touching_panel_message() -> None:
    """Concorrencia continua protegida: se `claim_service.claim_ticket` recusa
    (outro staff ja assumiu), a mensagem do painel nao e reeditada e o erro
    e mostrado ao usuario — comportamento inalterado pela otimizacao."""
    bot = MagicMock()
    ticket = _ticket()
    bot.ticket_service.get_by_channel_id = AsyncMock(return_value=ticket)
    bot.ticket_panel_service.get_panel_for_ticket = AsyncMock(return_value=None)
    bot.staff_service.ensure_staff = AsyncMock(return_value=_staff())
    bot.claim_service.claim_ticket = AsyncMock(
        side_effect=ClaimError("Este ticket ja esta em atendimento por outro membro da staff.")
    )

    member = _admin_member()
    interaction = _interaction_for_component(bot=bot, member=member)

    view = TicketActionsView()
    await view.claim.callback(interaction)

    interaction.message.edit.assert_not_called()
    interaction.followup.send.assert_awaited_once()
    assert "ja esta em atendimento" in interaction.followup.send.call_args.args[0]


# ============================ Incluir / Remover: auditoria em background ==============================


async def test_include_uses_record_background_not_record() -> None:
    bot = MagicMock()
    ticket = _ticket()
    bot.ticket_service.get_by_channel_id = AsyncMock(return_value=ticket)
    bot.audit_log_service.record = AsyncMock()
    bot.audit_log_service.record_background = MagicMock()

    target = MagicMock(spec=discord.Member)
    target.mention = "<@555>"
    target.id = 555

    interaction = MagicMock()
    interaction.client = bot
    interaction.user = _admin_member()
    interaction.channel_id = 999
    interaction.guild = MagicMock()
    interaction.guild.id = 1
    channel = MagicMock(spec=discord.TextChannel)
    channel.set_permissions = AsyncMock()
    channel.send = AsyncMock()
    channel.name = "ticket-pam"
    interaction.channel = channel
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    select = _IncludeUserSelect()
    select._values = [target]  # type: ignore[attr-defined]

    await select.callback(interaction)

    channel.set_permissions.assert_awaited_once()
    bot.audit_log_service.record_background.assert_called_once()
    bot.audit_log_service.record.assert_not_awaited()
    channel.send.assert_awaited_once()
    interaction.followup.send.assert_awaited_once()


async def test_remove_uses_record_background_not_record() -> None:
    bot = MagicMock()
    ticket = _ticket()
    bot.ticket_service.get_by_channel_id = AsyncMock(return_value=ticket)
    bot.audit_log_service.record = AsyncMock()
    bot.audit_log_service.record_background = MagicMock()

    target = MagicMock(spec=discord.Member)
    target.mention = "<@555>"
    target.id = 555
    target.guild_permissions.administrator = False

    interaction = MagicMock()
    interaction.client = bot
    interaction.user = _admin_member()
    interaction.channel_id = 999
    interaction.guild = MagicMock()
    interaction.guild.id = 1
    channel = MagicMock(spec=discord.TextChannel)
    channel.overwrites_for = MagicMock(return_value=discord.PermissionOverwrite(view_channel=True))
    channel.set_permissions = AsyncMock()
    channel.send = AsyncMock()
    channel.name = "ticket-pam"
    interaction.channel = channel
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    select = _RemoveUserSelect()
    select._values = [target]  # type: ignore[attr-defined]

    await select.callback(interaction)

    channel.set_permissions.assert_awaited_once()
    bot.audit_log_service.record_background.assert_called_once()
    bot.audit_log_service.record.assert_not_awaited()
    channel.send.assert_awaited_once()
    interaction.followup.send.assert_awaited_once()


async def test_remove_still_blocks_opener_and_admin_regardless_of_background_logging() -> None:
    bot = MagicMock()
    ticket = _ticket()
    bot.ticket_service.get_by_channel_id = AsyncMock(return_value=ticket)
    bot.audit_log_service.record_background = MagicMock()

    target = MagicMock(spec=discord.Member)
    target.id = ticket.opened_by_discord_id  # e o autor do ticket

    interaction = MagicMock()
    interaction.client = bot
    interaction.user = _admin_member()
    interaction.channel_id = 999
    interaction.guild = MagicMock()
    interaction.guild.id = 1
    channel = MagicMock(spec=discord.TextChannel)
    channel.set_permissions = AsyncMock()
    interaction.channel = channel
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    select = _RemoveUserSelect()
    select._values = [target]  # type: ignore[attr-defined]

    await select.callback(interaction)

    channel.set_permissions.assert_not_called()
    bot.audit_log_service.record_background.assert_not_called()
    interaction.followup.send.assert_awaited_once()
    assert "abriu o ticket" in interaction.followup.send.call_args.args[0]
