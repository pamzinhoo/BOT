from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import discord

from database.database import Database
from database.models.staff_activity import StaffActivityEvent
from database.models.ticket import Ticket, TicketApprovalStatus, TicketCategory, TicketStatus
from database.models.ticket_message import TicketMessage, TicketMessageKind
from database.models.ticket_panel import TicketPanel
from database.repositories.achievement_repository import AchievementRepository
from database.repositories.staff_activity_repository import StaffActivityRepository
from database.repositories.staff_stats_repository import StaffStatsRepository
from database.repositories.ticket_message_repository import TicketMessageRepository
from database.repositories.ticket_repository import TicketRepository
from utils.constants import TICKET_IMMEDIATE_CLOSE_SECONDS
from utils.formatter import running_average

_MILESTONE_ACHIEVEMENTS = {1: "first_ticket", 100: "tickets_100", 1000: "tickets_1000"}


class TicketNotFoundError(ValueError):
    """Ticket nao encontrado no banco."""


class TicketNotClaimedError(ValueError):
    """Ticket precisa ser assumido por um staff antes de ser fechado."""


@dataclass
class CloseResult:
    ticket: Ticket
    unlocked_achievements: list[str] = field(default_factory=list)


class TicketService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create_ticket(
        self,
        guild: discord.Guild,
        member: discord.Member,
        category: TicketCategory,
        ticket_category_channel: discord.CategoryChannel | None,
        staff_role_ids: list[int],
        *,
        panel: TicketPanel | None = None,
    ) -> tuple[Ticket, discord.TextChannel]:
        """Cria o canal do ticket + a linha no banco.

        `panel` e opcional de proposito: o fluxo legado (/painel-setup ->
        PainelView) chama sem ele e continua se comportando exatamente igual.
        Quando vem preenchido, o ticket fica vinculado ao painel (panel_id) e ja
        nasce PENDING se o painel exigir aprovacao."""
        overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
        }
        for role_id in staff_role_ids:
            role = guild.get_role(role_id)
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )

        prefix = panel.key if panel is not None else "ticket"
        channel_name = f"{prefix}-{member.name}"[:90].lower()
        channel = await guild.create_text_channel(
            name=channel_name,
            category=ticket_category_channel,
            overwrites=overwrites,
            reason=f"Ticket aberto por {member} ({category.value})",
        )

        approval_status = (
            TicketApprovalStatus.PENDING
            if panel is not None and panel.approval_enabled
            else TicketApprovalStatus.NONE
        )
        async with self._database.session() as session:
            ticket = await TicketRepository(session).add(
                Ticket(
                    guild_id=guild.id,
                    channel_id=channel.id,
                    opened_by_discord_id=member.id,
                    category=category,
                    panel_id=panel.id if panel is not None else None,
                    approval_status=approval_status,
                )
            )
        return ticket, channel

    async def set_approval_decision(
        self, channel_id: int, *, status: TicketApprovalStatus, reviewer_id: int
    ) -> Ticket:
        """Registra a decisao de Aprovar/Reprovar de um ticket vindo de painel
        com etapa de aprovacao. Nao mexe no status do ticket em si — aprovar ou
        reprovar nao fecha nada, o fluxo normal de fechamento continua valendo."""
        async with self._database.session() as session:
            ticket = await TicketRepository(session).get_by_channel_id(channel_id)
            if ticket is None:
                raise TicketNotFoundError("Ticket nao encontrado para este canal.")
            ticket.approval_status = status
            ticket.approval_reviewed_by = reviewer_id
            ticket.approval_reviewed_at = datetime.now(UTC)
            return ticket

    async def record_first_message(self, message: discord.Message, is_staff: bool) -> None:
        kind = TicketMessageKind.STAFF_FIRST if is_staff else TicketMessageKind.USER_FIRST
        async with self._database.session() as session:
            ticket_repo = TicketRepository(session)
            ticket = await ticket_repo.get_by_channel_id(message.channel.id)
            if ticket is None or ticket.status == TicketStatus.CLOSED:
                return
            message_repo = TicketMessageRepository(session)
            if await message_repo.exists(ticket.id, kind):
                return
            await message_repo.add(
                TicketMessage(
                    ticket_id=ticket.id,
                    kind=kind,
                    discord_message_id=message.id,
                    author_discord_id=message.author.id,
                    sent_at=message.created_at,
                )
            )
            if kind == TicketMessageKind.STAFF_FIRST and ticket.first_response_at is None:
                ticket.first_response_at = message.created_at

    async def close_ticket(self, channel_id: int, closed_by_discord_id: int) -> CloseResult:
        now = datetime.now(UTC)
        async with self._database.session() as session:
            ticket_repo = TicketRepository(session)
            ticket = await ticket_repo.get_by_channel_id(channel_id)
            if ticket is None:
                raise TicketNotFoundError("Ticket nao encontrado para este canal.")
            if ticket.claimed_by_staff_id is None:
                raise TicketNotClaimedError(
                    "Este ticket ainda nao foi assumido por ninguem. Assuma o ticket antes de fecha-lo."
                )

            was_previously_closed = ticket.closed_at is not None

            has_user_message = await TicketMessageRepository(session).exists(
                ticket.id, TicketMessageKind.USER_FIRST
            )
            elapsed = (now - ticket.created_at).total_seconds()
            counts = (
                not was_previously_closed
                and has_user_message
                and elapsed >= TICKET_IMMEDIATE_CLOSE_SECONDS
                and not ticket.deleted_before_service
            )

            ticket.status = TicketStatus.CLOSED
            ticket.closed_at = now
            ticket.closed_by_discord_id = closed_by_discord_id
            ticket.counts_for_stats = counts

            unlocked: list[str] = []

            if ticket.claimed_by_staff_id is not None and counts:
                stats_repo = StaffStatsRepository(session)
                stats = await stats_repo.get_or_create(ticket.claimed_by_staff_id)
                old_count = stats.tickets_fechados
                stats.tickets_fechados = old_count + 1
                if ticket.first_response_at is not None:
                    first_response_s = int(
                        (ticket.first_response_at - ticket.created_at).total_seconds()
                    )
                    stats.tempo_medio_primeira_resposta_s = int(
                        running_average(
                            stats.tempo_medio_primeira_resposta_s, old_count, first_response_s
                        )
                    )
                fechamento_s = int((now - ticket.created_at).total_seconds())
                stats.tempo_medio_fechamento_s = int(
                    running_average(stats.tempo_medio_fechamento_s, old_count, fechamento_s)
                )
                stats.ultimo_ticket_at = now
                if stats.ticket_atual_id == ticket.id:
                    stats.ticket_atual_id = None
                await StaffActivityRepository(session).log_event(
                    ticket.claimed_by_staff_id, StaffActivityEvent.CLOSED, now
                )

                today = now.date()
                is_new_day = stats.last_streak_date != today
                if stats.last_streak_date is None or stats.last_streak_date < today - timedelta(days=1):
                    new_streak = 1
                elif stats.last_streak_date == today - timedelta(days=1):
                    new_streak = stats.current_streak_days + 1
                else:
                    new_streak = stats.current_streak_days
                stats.current_streak_days = new_streak
                stats.best_streak_days = max(stats.best_streak_days, new_streak)
                stats.last_streak_date = today

                if is_new_day:
                    stats.total_active_days += 1

                if stats.current_day_date == today:
                    stats.current_day_ticket_count += 1
                else:
                    stats.current_day_date = today
                    stats.current_day_ticket_count = 1
                stats.best_day_ticket_count = max(stats.best_day_ticket_count, stats.current_day_ticket_count)

                achievement_key = _MILESTONE_ACHIEVEMENTS.get(stats.tickets_fechados)
                if achievement_key is not None:
                    achievement_repo = AchievementRepository(session)
                    if await achievement_repo.award(ticket.claimed_by_staff_id, achievement_key):
                        unlocked.append(achievement_key)
            elif ticket.claimed_by_staff_id is not None:
                stats_repo = StaffStatsRepository(session)
                stats = await stats_repo.get_or_create(ticket.claimed_by_staff_id)
                if stats.ticket_atual_id == ticket.id:
                    stats.ticket_atual_id = None

            return CloseResult(ticket=ticket, unlocked_achievements=unlocked)

    async def reopen_ticket(self, channel_id: int) -> Ticket:
        async with self._database.session() as session:
            ticket_repo = TicketRepository(session)
            ticket = await ticket_repo.get_by_channel_id(channel_id)
            if ticket is None:
                raise TicketNotFoundError("Ticket nao encontrado para este canal.")
            ticket.status = (
                TicketStatus.CLAIMED if ticket.claimed_by_staff_id is not None else TicketStatus.OPEN
            )
            ticket.closed_at = None
            ticket.closed_by_discord_id = None
            return ticket

    async def cancel_ticket(self, channel_id: int) -> Ticket:
        async with self._database.session() as session:
            ticket_repo = TicketRepository(session)
            ticket = await ticket_repo.get_by_channel_id(channel_id)
            if ticket is None:
                raise TicketNotFoundError("Ticket nao encontrado para este canal.")
            ticket.status = TicketStatus.CANCELLED
            ticket.counts_for_stats = False
            if ticket.claimed_by_staff_id is not None:
                stats = await StaffStatsRepository(session).get_or_create(
                    ticket.claimed_by_staff_id
                )
                stats.tickets_cancelados += 1
                if stats.ticket_atual_id == ticket.id:
                    stats.ticket_atual_id = None
            return ticket

    async def mark_deleted_before_service(self, channel_id: int) -> Ticket | None:
        async with self._database.session() as session:
            ticket_repo = TicketRepository(session)
            ticket = await ticket_repo.get_by_channel_id(channel_id)
            if ticket is None or ticket.status == TicketStatus.CLOSED:
                return None
            ticket.deleted_before_service = True
            ticket.status = TicketStatus.CANCELLED
            ticket.counts_for_stats = False
            return ticket

    async def get_by_id(self, ticket_id: uuid.UUID) -> Ticket | None:
        async with self._database.session() as session:
            return await TicketRepository(session).get_by_id(ticket_id)

    async def get_by_channel_id(self, channel_id: int) -> Ticket | None:
        async with self._database.session() as session:
            return await TicketRepository(session).get_by_channel_id(channel_id)

    async def list_open_by_guild(self, guild_id: int) -> list[Ticket]:
        async with self._database.session() as session:
            return await TicketRepository(session).list_open_by_guild(guild_id)

    async def count_open_by_member(self, guild_id: int, member_id: int) -> int:
        async with self._database.session() as session:
            return await TicketRepository(session).count_open_by_member(guild_id, member_id)

    async def list_awaiting_first_response(self, guild_id: int) -> list[Ticket]:
        async with self._database.session() as session:
            return await TicketRepository(session).list_awaiting_first_response(guild_id)

    async def mark_reminder_tier(self, channel_id: int, tier: int) -> None:
        async with self._database.session() as session:
            ticket = await TicketRepository(session).get_by_channel_id(channel_id)
            if ticket is not None:
                ticket.reminder_tier_sent = tier

    async def set_voice_channel(self, channel_id: int, voice_channel_id: int | None) -> None:
        async with self._database.session() as session:
            ticket = await TicketRepository(session).get_by_channel_id(channel_id)
            if ticket is not None:
                ticket.voice_channel_id = voice_channel_id
