from __future__ import annotations

import uuid
from dataclasses import dataclass

import discord

from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.punishment import Punishment, PunishmentStatus, PunishmentType
from database.models.punishment_appeal import PunishmentAppeal
from database.repositories.punishment_repository import PunishmentRepository
from services.audit_log_service import AuditLogService
from services.punishment_service import AppealError, PunishmentError, PunishmentService

PAGE_SIZE = 10

_FILTER_TYPES: dict[str, set[PunishmentType] | None] = {
    "todos": None,
    "ban": {PunishmentType.BAN, PunishmentType.BAN_TEMPORARIO},
    "timeout": {PunishmentType.TIMEOUT},
    "kick": {PunishmentType.KICK},
    "advertencia": {PunishmentType.ADVERTENCIA},
}


class PunishmentReviewError(ValueError):
    """Erro de negocio ao listar/decidir uma punicao em analise pelo painel /analises."""


@dataclass
class PendingPunishmentItem:
    punishment: Punishment
    appeal: PunishmentAppeal | None


@dataclass
class PunishmentReviewDecision:
    punishment: Punishment
    appeal: PunishmentAppeal | None


class PunishmentReviewService:
    """Camada de negocio do painel /analises. Nao guarda regra de UI — so busca,
    pagina e decide (aceita/nega) punições PENDING_REVIEW, reaproveitando o fluxo
    ja existente em PunishmentService (accept_appeal/deny_appeal/resolve_review)."""

    def __init__(
        self,
        database: Database,
        punishment_service: PunishmentService,
        audit_log_service: AuditLogService,
    ) -> None:
        self._database = database
        self._punishment_service = punishment_service
        self._audit_log_service = audit_log_service

    @staticmethod
    def filter_types(filtro: str) -> set[PunishmentType] | None:
        """Mapeia o valor do parametro `filtro` do /analises pro conjunto de tipos
        aceitos na query. 'todos' (ou qualquer valor desconhecido) nao filtra por tipo."""
        return _FILTER_TYPES.get(filtro)

    @staticmethod
    def paginate(
        items: list[PendingPunishmentItem], page: int, page_size: int = PAGE_SIZE
    ) -> tuple[list[PendingPunishmentItem], int]:
        """Pagina uma lista ja carregada. Pagina fora do intervalo e presa em [1, total_pages]."""
        total_pages = max(1, (len(items) + page_size - 1) // page_size)
        page = min(max(page, 1), total_pages)
        start = (page - 1) * page_size
        return items[start : start + page_size], total_pages

    @staticmethod
    def is_self_review(punishment: Punishment, reviewer_id: int) -> bool:
        return punishment.staff_id == reviewer_id

    @staticmethod
    def divergent_user_ids(role_member_ids: set[int], covered_user_ids: set[int]) -> set[int]:
        """IDs de quem tem o cargo de análise no Discord mas nenhuma punição
        PENDING_REVIEW correspondente no banco — só um alerta de inconsistência
        (cargo dado na mão, ou punição corrompida). O banco continua sendo a
        única fonte de verdade pro que aparece na lista principal."""
        return role_member_ids - covered_user_ids

    async def list_pending(
        self, guild_id: int, *, filtro: str = "todos", staff_id: int | None = None
    ) -> list[PendingPunishmentItem]:
        types = self.filter_types(filtro)
        async with self._database.session() as session:
            punishments = await PunishmentRepository(session).list_pending_review(
                guild_id, types=types, staff_id=staff_id
            )
        items: list[PendingPunishmentItem] = []
        for punishment in punishments:
            appeal = await self._punishment_service.get_pending_appeal(punishment.id)
            items.append(PendingPunishmentItem(punishment=punishment, appeal=appeal))
        return items

    async def get_item(self, punishment_id: uuid.UUID) -> PendingPunishmentItem | None:
        punishment = await self._punishment_service.get_by_id(punishment_id)
        if punishment is None:
            return None
        appeal = await self._punishment_service.get_pending_appeal(punishment_id)
        return PendingPunishmentItem(punishment=punishment, appeal=appeal)

    async def _load_and_validate(
        self, punishment_id: uuid.UUID, reviewer: discord.Member
    ) -> tuple[Punishment, PunishmentAppeal | None]:
        punishment = await self._punishment_service.get_by_id(punishment_id)
        if punishment is None:
            raise PunishmentReviewError("Punição não encontrada.")
        if punishment.status != PunishmentStatus.PENDING_REVIEW:
            raise PunishmentReviewError("Essa punição não está mais em análise.")
        if self.is_self_review(punishment, reviewer.id):
            raise PunishmentReviewError("Você não pode analisar o recurso da sua própria punição.")
        appeal = await self._punishment_service.get_pending_appeal(punishment_id)
        return punishment, appeal

    async def accept(
        self,
        *,
        guild: discord.Guild,
        punishment_id: uuid.UUID,
        reviewer: discord.Member,
        review_role_id: int | None,
    ) -> PunishmentReviewDecision:
        punishment, appeal = await self._load_and_validate(punishment_id, reviewer)
        try:
            if appeal is not None:
                result = await self._punishment_service.accept_appeal(
                    guild=guild,
                    appeal_id=appeal.id,
                    reviewer=reviewer,
                    review_role_id=review_role_id,
                )
                punishment, appeal = result.punishment, result.appeal
            else:
                punishment = await self._punishment_service.resolve_review(
                    guild=guild,
                    punishment_id=punishment_id,
                    approved=True,
                    reviewer_id=reviewer.id,
                    reviewer_name=str(reviewer),
                    reason="Recurso aceito pelo painel /analises",
                    review_role_id=review_role_id,
                )
        except (AppealError, PunishmentError) as exc:
            raise PunishmentReviewError(str(exc)) from exc

        await self._audit_log_service.record(
            guild_id=guild.id,
            category=AuditLogCategory.PUNISHMENT_REVIEW,
            action="ACCEPT_APPEAL_FROM_PANEL",
            executor_id=reviewer.id,
            executor_name=str(reviewer),
            target_id=punishment.user_id,
            target_name=punishment.user_name,
            details={"punishment_id": str(punishment.id), "punishment_code": punishment.punishment_code},
        )
        return PunishmentReviewDecision(punishment=punishment, appeal=appeal)

    async def deny(
        self,
        *,
        guild: discord.Guild,
        punishment_id: uuid.UUID,
        reviewer: discord.Member,
        reason: str,
        review_role_id: int | None,
    ) -> PunishmentReviewDecision:
        punishment, appeal = await self._load_and_validate(punishment_id, reviewer)
        try:
            if appeal is not None:
                result = await self._punishment_service.deny_appeal(
                    guild=guild,
                    appeal_id=appeal.id,
                    reviewer=reviewer,
                    reason=reason,
                    review_role_id=review_role_id,
                )
                punishment, appeal = result.punishment, result.appeal
            else:
                punishment = await self._punishment_service.resolve_review(
                    guild=guild,
                    punishment_id=punishment_id,
                    approved=False,
                    reviewer_id=reviewer.id,
                    reviewer_name=str(reviewer),
                    reason=reason,
                    review_role_id=review_role_id,
                )
        except (AppealError, PunishmentError) as exc:
            raise PunishmentReviewError(str(exc)) from exc

        await self._audit_log_service.record(
            guild_id=guild.id,
            category=AuditLogCategory.PUNISHMENT_REVIEW,
            action="DENY_APPEAL_FROM_PANEL",
            executor_id=reviewer.id,
            executor_name=str(reviewer),
            target_id=punishment.user_id,
            target_name=punishment.user_name,
            reason=reason,
            details={"punishment_id": str(punishment.id), "punishment_code": punishment.punishment_code},
        )
        return PunishmentReviewDecision(punishment=punishment, appeal=appeal)
