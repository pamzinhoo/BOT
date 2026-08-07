from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import discord
from sqlalchemy.exc import IntegrityError

from core.logger import get_logger
from database.database import Database
from database.models.enquete_settings import EnqueteSettings
from database.models.poll import Poll, PollOption, PollStatus, PollVisibility, PollVote
from database.repositories.enquete_settings_repository import EnqueteSettingsRepository
from database.repositories.poll_repository import (
    PollOptionRepository,
    PollRepository,
    PollVoteRepository,
)
from services.subscription_service import SubscriptionService
from services.vote_weight_service import VoteWeightService

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("poll_service")

MIN_OPTIONS = 2
MAX_OPTIONS = 10


class EnqueteDisabledError(ValueError):
    pass


class InvalidOptionsError(ValueError):
    pass


class AlreadyVotedError(ValueError):
    pass


def render_poll_placeholders(
    template: str,
    *,
    poll: Poll,
    creator: discord.Member | discord.User | None = None,
    winner: str | None = None,
    votes: int = 0,
    participants: int = 0,
) -> str:
    values = {
        "{title}": poll.title,
        "{creator}": creator.mention if creator is not None else f"<@{poll.creator_id}>",
        "{winner}": winner or "—",
        "{votes}": str(votes),
        "{participants}": str(participants),
    }
    result = template
    for placeholder, value in values.items():
        result = result.replace(placeholder, value)
    return result


class PollService:
    """Regras de negocio do sistema de Enquetes. Tambem e dono do CRUD de
    EnqueteSettings, mesmo padrao de SubscriptionService possuir
    MonetizationSettings — cog/painel nunca falam direto com os repositorios."""

    def __init__(
        self,
        database: Database,
        bot: LimerenceBot,
        vote_weight_service: VoteWeightService,
        subscription_service: SubscriptionService,
    ) -> None:
        self._database = database
        self._bot = bot
        self._weights = vote_weight_service
        self._subscriptions = subscription_service

    # --- configuracao -------------------------------------------------------

    async def get_settings(self, guild_id: int) -> EnqueteSettings:
        async with self._database.session() as session:
            return await EnqueteSettingsRepository(session).get_or_create(guild_id)

    async def update_settings(self, guild_id: int, **fields: object) -> EnqueteSettings:
        async with self._database.session() as session:
            repo = EnqueteSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
            await session.flush()
            await session.refresh(settings)
            return settings

    # --- criacao --------------------------------------------------------

    async def create_poll(
        self,
        *,
        guild_id: int,
        creator_id: int,
        channel_id: int,
        title: str,
        description: str | None,
        options: list[str],
        duration: timedelta,
        visibility: PollVisibility = PollVisibility.PUBLIC,
        required_role_id: int | None = None,
        required_plan_id: uuid.UUID | None = None,
    ) -> tuple[Poll, list[PollOption]]:
        cleaned_options = [opt.strip() for opt in options if opt.strip()]
        if len(cleaned_options) < MIN_OPTIONS:
            raise InvalidOptionsError(f"A enquete precisa de pelo menos {MIN_OPTIONS} opções.")
        if len(cleaned_options) > MAX_OPTIONS:
            raise InvalidOptionsError(f"A enquete pode ter no máximo {MAX_OPTIONS} opções.")

        settings = await self.get_settings(guild_id)
        if not settings.enabled:
            raise EnqueteDisabledError("O sistema de enquetes está desativado neste servidor.")

        async with self._database.session() as session:
            poll_repo = PollRepository(session)
            poll = await poll_repo.add(
                Poll(
                    guild_id=guild_id,
                    creator_id=creator_id,
                    channel_id=channel_id,
                    title=title,
                    description=description,
                    visibility=visibility,
                    required_role_id=required_role_id,
                    required_plan_id=required_plan_id,
                    weight_mode=settings.default_weight_mode,
                    expires_at=datetime.now(UTC) + duration,
                )
            )
            option_repo = PollOptionRepository(session)
            created_options = [
                await option_repo.add(PollOption(poll_id=poll.id, name=name, position=position))
                for position, name in enumerate(cleaned_options)
            ]
            await session.refresh(poll)
        return poll, created_options

    async def set_message_id(self, poll_id: uuid.UUID, message_id: int) -> None:
        async with self._database.session() as session:
            repo = PollRepository(session)
            poll = await repo.get_by_id(poll_id)
            if poll is not None:
                poll.message_id = message_id
                await session.flush()

    # --- consulta ---------------------------------------------------------

    async def get_poll(self, poll_id: uuid.UUID) -> Poll | None:
        async with self._database.session() as session:
            return await PollRepository(session).get_by_id(poll_id)

    async def list_options(self, poll_id: uuid.UUID) -> list[PollOption]:
        async with self._database.session() as session:
            return await PollOptionRepository(session).list_by_poll(poll_id)

    async def list_open_expiring(self, before: datetime) -> list[Poll]:
        async with self._database.session() as session:
            return await PollRepository(session).list_open_expiring(before)

    # --- votacao ---------------------------------------------------------

    async def can_vote(self, poll: Poll, member: discord.Member) -> tuple[bool, str | None]:
        if poll.status != PollStatus.OPEN:
            return False, "Essa enquete já foi encerrada."
        if poll.visibility == PollVisibility.PUBLIC:
            return True, None
        if poll.visibility == PollVisibility.ROLE_RESTRICTED:
            if poll.required_role_id is not None and any(
                role.id == poll.required_role_id for role in member.roles
            ):
                return True, None
            return False, "Você não tem o cargo necessário pra votar nessa enquete."
        if poll.visibility == PollVisibility.PREMIUM:
            if poll.required_plan_id is not None:
                subscriptions = await self._subscriptions.list_active_subscriptions(
                    poll.guild_id, member.id
                )
                if any(sub.plan_id == poll.required_plan_id for sub in subscriptions):
                    return True, None
            return False, "Você precisa de uma assinatura ativa do plano exigido pra votar."
        return False, "Tipo de enquete desconhecido."

    async def cast_vote(self, poll: Poll, option_id: uuid.UUID, member: discord.Member) -> PollVote:
        weight = await self._weights.resolve_weight_for_member(poll.guild_id, member)
        try:
            async with self._database.session() as session:
                vote = await PollVoteRepository(session).add(
                    PollVote(poll_id=poll.id, option_id=option_id, user_id=member.id, weight=weight)
                )
        except IntegrityError as exc:
            raise AlreadyVotedError("Você já votou nessa enquete.") from exc
        return vote

    async def weighted_totals(self, poll_id: uuid.UUID) -> dict[uuid.UUID, int]:
        async with self._database.session() as session:
            return await PollVoteRepository(session).weighted_totals(poll_id)

    async def count_participants(self, poll_id: uuid.UUID) -> int:
        async with self._database.session() as session:
            return await PollVoteRepository(session).count_participants(poll_id)

    # --- fechamento ---------------------------------------------------------

    async def close_poll(self, poll_id: uuid.UUID) -> Poll | None:
        async with self._database.session() as session:
            repo = PollRepository(session)
            poll = await repo.get_by_id(poll_id)
            if poll is None or poll.status != PollStatus.OPEN:
                return poll
            poll.status = PollStatus.CLOSED
            poll.closed_at = datetime.now(UTC)
            await session.flush()
            await session.refresh(poll)
        return poll

    # --- reacao a mudanca de cargo (weight_mode == "LIVE") -------------------

    async def on_member_role_change(self, member: discord.Member) -> None:
        async with self._database.session() as session:
            vote_repo = PollVoteRepository(session)
            live_votes = await vote_repo.list_open_live_votes_for_user(member.id)
            if not live_votes:
                return
            new_weight = await self._weights.resolve_weight_for_member(member.guild.id, member)
            for vote in live_votes:
                vote.weight = new_weight
            await session.flush()
