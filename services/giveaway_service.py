from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import discord
from sqlalchemy.exc import IntegrityError

from core.logger import get_logger
from database.database import Database
from database.models.giveaway import (
    Giveaway,
    GiveawayEntry,
    GiveawayPrizeType,
    GiveawayStatus,
    GiveawayWinner,
)
from database.repositories.giveaway_repository import (
    GiveawayEntryRepository,
    GiveawayRepository,
    GiveawayWinnerRepository,
)

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("giveaway_service")

_RNG = secrets.SystemRandom()


def _weighted_sample(candidates: list[tuple[int, int]], k: int) -> list[int]:
    """Sorteio sem reposicao ponderado pelo peso de voto VIP (roulette wheel):
    cada rodada sorteia 1 vencedor com chance proporcional ao peso, remove ele
    do pool e repete. Peso 1 pra todos == sorteio uniforme de sempre."""
    pool = list(candidates)
    winners: list[int] = []
    for _ in range(min(k, len(pool))):
        total = sum(weight for _, weight in pool)
        pick = _RNG.uniform(0, total)
        upto = 0.0
        for i, (user_id, weight) in enumerate(pool):
            upto += weight
            if upto >= pick:
                winners.append(user_id)
                pool.pop(i)
                break
    return winners


class InvalidWinnersCountError(ValueError):
    pass


class AlreadyEnteredError(ValueError):
    pass


class GiveawayService:
    """Regras de negocio do sistema de Sorteios. Cog/painel nunca falam
    direto com os repositorios, mesmo padrao de PollService/VerificationService."""

    def __init__(self, database: Database, bot: "LimerenceBot") -> None:
        self._database = database
        self._bot = bot

    # --- criacao -----------------------------------------------------------

    async def create_giveaway(
        self,
        *,
        guild_id: int,
        creator_id: int,
        channel_id: int,
        title: str,
        description: str | None,
        duration: timedelta,
        winners_count: int,
        allowed_role_ids: list[int],
        prize_type: GiveawayPrizeType,
        prize_role_id: int | None = None,
        prize_text: str | None = None,
    ) -> Giveaway:
        if winners_count < 1:
            raise InvalidWinnersCountError("A quantidade de vencedores precisa ser pelo menos 1.")

        async with self._database.session() as session:
            giveaway = await GiveawayRepository(session).add(
                Giveaway(
                    guild_id=guild_id,
                    creator_id=creator_id,
                    channel_id=channel_id,
                    title=title,
                    description=description,
                    prize_type=prize_type,
                    prize_role_id=prize_role_id,
                    prize_text=prize_text,
                    allowed_role_ids=allowed_role_ids,
                    winners_count=winners_count,
                    expires_at=datetime.now(UTC) + duration,
                )
            )
            await session.refresh(giveaway)
        return giveaway

    async def set_message_id(self, giveaway_id: uuid.UUID, message_id: int) -> None:
        async with self._database.session() as session:
            repo = GiveawayRepository(session)
            giveaway = await repo.get_by_id(giveaway_id)
            if giveaway is not None:
                giveaway.message_id = message_id
                await session.flush()

    # --- consulta ------------------------------------------------------------

    async def get_giveaway(self, giveaway_id: uuid.UUID) -> Giveaway | None:
        async with self._database.session() as session:
            return await GiveawayRepository(session).get_by_id(giveaway_id)

    async def list_by_guild(self, guild_id: int) -> list[Giveaway]:
        async with self._database.session() as session:
            return await GiveawayRepository(session).list_by_guild(guild_id)

    async def list_open_expiring(self, before: datetime) -> list[Giveaway]:
        async with self._database.session() as session:
            return await GiveawayRepository(session).list_open_expiring(before)

    async def count_entries(self, giveaway_id: uuid.UUID) -> int:
        async with self._database.session() as session:
            return await GiveawayEntryRepository(session).count_by_giveaway(giveaway_id)

    # --- participacao ---------------------------------------------------------

    async def can_enter(self, giveaway: Giveaway, member: discord.Member) -> tuple[bool, str | None]:
        if giveaway.status != GiveawayStatus.OPEN:
            return False, "Esse sorteio já foi encerrado."
        if not giveaway.allowed_role_ids:
            return True, None
        member_role_ids = {role.id for role in member.roles}
        if member_role_ids & set(giveaway.allowed_role_ids):
            return True, None
        return False, "Você não tem o cargo necessário pra participar desse sorteio."

    async def enter(self, giveaway: Giveaway, member: discord.Member) -> GiveawayEntry:
        weight = await self._bot.vote_weight_service.resolve_weight_for_member(
            giveaway.guild_id, member
        )
        try:
            async with self._database.session() as session:
                entry = await GiveawayEntryRepository(session).add(
                    GiveawayEntry(giveaway_id=giveaway.id, user_id=member.id, weight=weight)
                )
        except IntegrityError as exc:
            raise AlreadyEnteredError("Você já está participando desse sorteio.") from exc
        return entry

    # --- encerramento e sorteio -------------------------------------------------

    async def close_and_draw(self, giveaway_id: uuid.UUID) -> tuple[Giveaway, list[int]] | None:
        async with self._database.session() as session:
            repo = GiveawayRepository(session)
            giveaway = await repo.get_by_id_locked(giveaway_id)
            if giveaway is None or giveaway.status != GiveawayStatus.OPEN:
                return None
            entries = await GiveawayEntryRepository(session).list_by_giveaway(giveaway_id)
            candidates = [(entry.user_id, entry.weight) for entry in entries]
            winners = _weighted_sample(candidates, giveaway.winners_count)

            winner_repo = GiveawayWinnerRepository(session)
            for user_id in winners:
                await winner_repo.add(GiveawayWinner(giveaway_id=giveaway.id, user_id=user_id))

            giveaway.status = GiveawayStatus.CLOSED
            giveaway.closed_at = datetime.now(UTC)
            await session.flush()
            await session.refresh(giveaway)

        for user_id in winners:
            await self._award_prize(giveaway, user_id)

        return giveaway, winners

    async def reroll(self, giveaway_id: uuid.UUID) -> tuple[Giveaway, list[int]] | None:
        async with self._database.session() as session:
            repo = GiveawayRepository(session)
            giveaway = await repo.get_by_id_locked(giveaway_id)
            if giveaway is None or giveaway.status != GiveawayStatus.CLOSED:
                return None
            entries = await GiveawayEntryRepository(session).list_by_giveaway(giveaway_id)
            candidates = [(entry.user_id, entry.weight) for entry in entries]

            winner_repo = GiveawayWinnerRepository(session)
            already_won = set(await winner_repo.list_user_ids_by_giveaway(giveaway_id))
            pool = [c for c in candidates if c[0] not in already_won] or candidates
            winners = _weighted_sample(pool, giveaway.winners_count)

            for user_id in winners:
                await winner_repo.add(GiveawayWinner(giveaway_id=giveaway.id, user_id=user_id))
            await session.flush()
            await session.refresh(giveaway)

        for user_id in winners:
            await self._award_prize(giveaway, user_id)

        return giveaway, winners

    async def list_winners(self, giveaway_id: uuid.UUID) -> list[int]:
        async with self._database.session() as session:
            return await GiveawayWinnerRepository(session).list_user_ids_by_giveaway(giveaway_id)

    # --- premiacao -------------------------------------------------------------

    async def _award_prize(self, giveaway: Giveaway, user_id: int) -> None:
        if giveaway.prize_type != GiveawayPrizeType.ROLE or giveaway.prize_role_id is None:
            return
        guild = self._bot.get_guild(giveaway.guild_id)
        if guild is None:
            return
        role = guild.get_role(giveaway.prize_role_id)
        if role is None:
            return
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.HTTPException:
                logger.warning("Não foi possível localizar o membro %s pra entregar prêmio de sorteio.", user_id)
                return
        if role in member.roles:
            return
        try:
            await member.add_roles(role, reason="Sorteio: prêmio")
        except discord.Forbidden:
            logger.warning("Sem permissão para entregar cargo-prêmio do sorteio na guild %s.", giveaway.guild_id)
        except discord.HTTPException:
            logger.exception("Falha ao entregar cargo-prêmio do sorteio na guild %s.", giveaway.guild_id)
