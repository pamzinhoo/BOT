from __future__ import annotations

import random
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import discord

from core.logger import get_logger
from database.database import Database
from database.models.punishment import (
    UNRESOLVED_STATUSES,
    Punishment,
    PunishmentStatus,
    PunishmentType,
)
from database.models.punishment_appeal import AppealMethod, AppealStatus, PunishmentAppeal
from database.models.punishment_review_role import PunishmentReviewRole
from database.repositories.punishment_appeal_repository import PunishmentAppealRepository
from database.repositories.punishment_repository import PunishmentRepository
from database.repositories.punishment_review_role_repository import PunishmentReviewRoleRepository

_CODE_PREFIXES = {
    PunishmentType.BAN: "BAN",
    PunishmentType.BAN_TEMPORARIO: "BAN",
    PunishmentType.TIMEOUT: "TIMEOUT",
    PunishmentType.KICK: "KICK",
    PunishmentType.ADVERTENCIA: "ADV",
}

_TYPES_REQUIRING_DURATION = {PunishmentType.BAN_TEMPORARIO, PunishmentType.TIMEOUT}
_DISCORD_TIMEOUT_MAX = timedelta(days=28)

logger = get_logger("punishment_service")


class PunishmentError(ValueError):
    """Erro de negocio ao aplicar/revogar uma punicao (mostrado direto pro staff)."""


class AppealError(ValueError):
    """Erro de negocio no fluxo de recurso (Etapa 20 — anti-abuso)."""


@dataclass
class AppealDecisionResult:
    punishment: Punishment
    appeal: PunishmentAppeal


class PunishmentService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def _generate_code(self, session, ptype: PunishmentType) -> str:
        prefix = _CODE_PREFIXES[ptype]
        repo = PunishmentRepository(session)
        for _ in range(10):
            candidate = f"{prefix}-{random.randint(10000, 99999)}"
            if not await repo.code_exists(candidate):
                return candidate
        raise PunishmentError("Não foi possível gerar um ID único para a punição. Tente novamente.")

    async def create_pending(
        self,
        *,
        guild: discord.Guild,
        staff: discord.Member,
        target: discord.Member,
        ptype: PunishmentType,
        reason: str,
        proofs: list[str],
        duration: timedelta | None,
        max_timeout: timedelta | None = None,
    ) -> Punishment:
        """Etapa 3: cria a punicao em status PENDING apos a 1a confirmacao passar
        nas validacoes. Nenhuma acao e executada no Discord ainda."""
        if ptype in _TYPES_REQUIRING_DURATION and duration is None:
            raise PunishmentError("Duração é obrigatória para esse tipo de punição.")

        if ptype == PunishmentType.TIMEOUT and duration is not None:
            limit = min(max_timeout, _DISCORD_TIMEOUT_MAX) if max_timeout else _DISCORD_TIMEOUT_MAX
            if duration > limit:
                raise PunishmentError(f"Duração do timeout excede o máximo permitido ({limit}).")

        async with self._database.session() as session:
            repo = PunishmentRepository(session)
            if await repo.has_open_punishment_of_type(guild.id, target.id, ptype):
                raise PunishmentError("Já existe uma punição desse tipo em aberto para este usuário.")

            code = await self._generate_code(session, ptype)
            punishment = await repo.add(
                Punishment(
                    guild_id=guild.id,
                    punishment_code=code,
                    user_id=target.id,
                    user_name=str(target),
                    staff_id=staff.id,
                    staff_name=str(staff),
                    type=ptype,
                    reason=reason,
                    proofs=proofs,
                    duration_seconds=int(duration.total_seconds()) if duration else None,
                    status=PunishmentStatus.PENDING,
                    first_confirmed_at=datetime.now(UTC),
                )
            )
            await session.flush()
            await session.refresh(punishment)
        return punishment

    async def create_pending_review(
        self,
        *,
        guild: discord.Guild,
        staff: discord.Member,
        target: discord.Member,
        ptype: PunishmentType,
        reason: str,
        proofs: list[str],
        duration: timedelta | None,
        max_timeout: timedelta | None = None,
        review_timeout_minutes: int,
    ) -> Punishment:
        """Etapa 22: cria a punicao ja em PENDING_REVIEW — o usuario e isolado (cargo de
        analise) mas a acao real (ban/kick/timeout) so acontece se o recurso for negado
        ou o prazo expirar sem recurso."""
        if ptype in _TYPES_REQUIRING_DURATION and duration is None:
            raise PunishmentError("Duração é obrigatória para esse tipo de punição.")
        if ptype == PunishmentType.TIMEOUT and duration is not None:
            limit = min(max_timeout, _DISCORD_TIMEOUT_MAX) if max_timeout else _DISCORD_TIMEOUT_MAX
            if duration > limit:
                raise PunishmentError(f"Duração do timeout excede o máximo permitido ({limit}).")

        async with self._database.session() as session:
            repo = PunishmentRepository(session)
            if await repo.has_open_punishment_of_type(guild.id, target.id, ptype):
                raise PunishmentError("Já existe uma punição desse tipo em aberto para este usuário.")

            code = await self._generate_code(session, ptype)
            now = datetime.now(UTC)
            punishment = await repo.add(
                Punishment(
                    guild_id=guild.id,
                    punishment_code=code,
                    user_id=target.id,
                    user_name=str(target),
                    staff_id=staff.id,
                    staff_name=str(staff),
                    type=ptype,
                    reason=reason,
                    proofs=proofs,
                    duration_seconds=int(duration.total_seconds()) if duration else None,
                    status=PunishmentStatus.PENDING_REVIEW,
                    first_confirmed_at=now,
                    second_confirmed_at=now,
                    review_deadline_at=now + timedelta(minutes=review_timeout_minutes),
                )
            )
            await session.flush()
            await session.refresh(punishment)
        return punishment

    async def isolate_member(
        self,
        *,
        guild: discord.Guild,
        punishment_id: uuid.UUID,
        member: discord.Member,
        review_role_id: int,
    ) -> None:
        """Aplica o cargo de analise e remove os demais cargos do membro, salvando os
        originais em punishment_review_roles pra restaurar depois (Etapa 22)."""
        review_role = guild.get_role(review_role_id)
        if review_role is None:
            raise PunishmentError("Cargo de análise configurado não existe mais neste servidor.")

        original_roles = [role for role in member.roles if role.id != guild.default_role.id]

        async with self._database.session() as session:
            role_repo = PunishmentReviewRoleRepository(session)
            for role in original_roles:
                await role_repo.add(
                    PunishmentReviewRole(punishment_id=punishment_id, user_id=member.id, role_id=role.id)
                )
            await session.flush()

        try:
            if original_roles:
                await member.remove_roles(*original_roles, reason="Isolamento para análise de punição")
            await member.add_roles(review_role, reason="Isolamento para análise de punição")
        except discord.Forbidden as exc:
            raise PunishmentError(
                "O bot não tem permissão para alterar os cargos deste membro (verifique a hierarquia)."
            ) from exc
        except discord.HTTPException as exc:
            logger.exception("Falha na API do Discord ao isolar o membro.")
            raise PunishmentError("Falha na API do Discord ao isolar o membro.") from exc

    async def _restore_review_roles(
        self,
        session,
        *,
        guild: discord.Guild,
        punishment_id: uuid.UUID,
        user_id: int,
        review_role_id: int | None,
    ) -> None:
        role_repo = PunishmentReviewRoleRepository(session)
        saved_roles = await role_repo.list_by_punishment(punishment_id)
        member = guild.get_member(user_id)
        if member is not None:
            roles_to_restore = [guild.get_role(r.role_id) for r in saved_roles]
            roles_to_restore = [r for r in roles_to_restore if r is not None]
            try:
                if roles_to_restore:
                    await member.add_roles(*roles_to_restore, reason="Restauração pós-análise de punição")
                review_role = guild.get_role(review_role_id) if review_role_id else None
                if review_role is not None and review_role in member.roles:
                    await member.remove_roles(review_role, reason="Restauração pós-análise de punição")
            except discord.HTTPException:
                pass
        await role_repo.delete_by_punishment(punishment_id)

    async def resolve_review(
        self,
        *,
        guild: discord.Guild,
        punishment_id: uuid.UUID,
        approved: bool,
        reviewer_id: int | None,
        reviewer_name: str,
        reason: str | None,
        review_role_id: int | None,
    ) -> Punishment:
        """Resolve uma punicao PENDING_REVIEW (Etapa 22): aceita (revoga e restaura os
        cargos) ou nega (restaura os cargos e só então aplica a punição real de fato).
        Usado tanto no aceite/negativa manual do recurso quanto na expiração automática
        do ReviewExpirationTask (reviewer_id=None nesse caso)."""
        async with self._database.session() as session:
            punishment = await PunishmentRepository(session).get_by_id(punishment_id)
            if punishment is None:
                raise PunishmentError("Punição não encontrada.")
            if punishment.guild_id != guild.id:
                # defesa em profundidade: nunca aplicar a acao (ban/kick) usando
                # a guild de quem chamou se a punicao pertence a outra guild.
                raise PunishmentError("Punição não encontrada.")
            if punishment.status != PunishmentStatus.PENDING_REVIEW:
                raise PunishmentError("Essa punição não está mais em análise.")

            await self._restore_review_roles(
                session,
                guild=guild,
                punishment_id=punishment_id,
                user_id=punishment.user_id,
                review_role_id=review_role_id,
            )

            now = datetime.now(UTC)
            if approved:
                punishment.status = PunishmentStatus.REVOKED
                punishment.revoked_by_id = reviewer_id
                punishment.revoked_by_name = reviewer_name
                punishment.revoke_reason = reason or "Recurso aceito"
                punishment.revoked_at = now
            else:
                member = guild.get_member(punishment.user_id)
                duration = (
                    timedelta(seconds=punishment.duration_seconds)
                    if punishment.duration_seconds
                    else None
                )
                try:
                    if punishment.type in (PunishmentType.BAN, PunishmentType.BAN_TEMPORARIO):
                        target = member or discord.Object(id=punishment.user_id)
                        await guild.ban(target, reason=punishment.reason, delete_message_seconds=0)
                    elif punishment.type == PunishmentType.KICK and member is not None:
                        await guild.kick(member, reason=punishment.reason)
                    elif punishment.type == PunishmentType.TIMEOUT and member is not None:
                        await member.timeout(duration, reason=punishment.reason)
                except discord.Forbidden as exc:
                    raise PunishmentError(
                        "O bot não tem permissão para aplicar essa punição neste membro."
                    ) from exc
                except discord.HTTPException as exc:
                    logger.exception("Falha na API do Discord ao aplicar a punicao.")
                    raise PunishmentError("Falha na API do Discord ao aplicar a punição.") from exc

                punishment.status = PunishmentStatus.ACTIVE
                punishment.second_confirmed_at = now
                punishment.expires_at = now + duration if duration is not None else None

            await session.flush()
            await session.refresh(punishment)
        return punishment

    async def list_expired_pending_reviews(self) -> list[Punishment]:
        async with self._database.session() as session:
            return await PunishmentRepository(session).list_expired_pending_reviews(datetime.now(UTC))

    async def record_dm_result(
        self, punishment_id: uuid.UUID, *, sent: bool, failure_reason: str | None
    ) -> Punishment:
        """Etapa 4: registra o resultado da tentativa de aviso por DM. Se enviada,
        avanca o status pra NOTIFIED; se falhar, permanece PENDING com o motivo salvo."""
        async with self._database.session() as session:
            punishment = await PunishmentRepository(session).get_by_id(punishment_id)
            if punishment is None:
                raise PunishmentError("Punição não encontrada.")
            punishment.dm_sent = sent
            punishment.dm_sent_at = datetime.now(UTC) if sent else None
            punishment.dm_failure_reason = None if sent else failure_reason
            if sent:
                punishment.status = PunishmentStatus.NOTIFIED
            await session.flush()
            await session.refresh(punishment)
        return punishment

    async def apply_pending(
        self, *, guild: discord.Guild, punishment_id: uuid.UUID, target: discord.Member
    ) -> Punishment:
        """Etapa 5: 2a confirmacao. Reexecuta o anti-erro (punicao ainda pendente) e so
        entao aplica de fato a acao no Discord."""
        async with self._database.session() as session:
            punishment = await PunishmentRepository(session).get_by_id(punishment_id)
            if punishment is None:
                raise PunishmentError("Punição não encontrada.")
            if punishment.guild_id != guild.id:
                raise PunishmentError("Punição não encontrada.")
            if punishment.status not in UNRESOLVED_STATUSES:
                raise PunishmentError("Essa punição já foi processada (não está mais pendente).")

            reason = punishment.reason
            duration = (
                timedelta(seconds=punishment.duration_seconds) if punishment.duration_seconds else None
            )
            try:
                if punishment.type in (PunishmentType.BAN, PunishmentType.BAN_TEMPORARIO):
                    await guild.ban(target, reason=reason, delete_message_seconds=0)
                elif punishment.type == PunishmentType.KICK:
                    await guild.kick(target, reason=reason)
                elif punishment.type == PunishmentType.TIMEOUT:
                    await target.timeout(duration, reason=reason)
            except discord.Forbidden as exc:
                raise PunishmentError(
                    "O bot não tem permissão para aplicar essa punição neste membro (verifique a hierarquia de cargos do bot)."
                ) from exc
            except discord.HTTPException as exc:
                logger.exception("Falha na API do Discord ao aplicar a punicao.")
                raise PunishmentError("Falha na API do Discord ao aplicar a punição.") from exc

            now = datetime.now(UTC)
            punishment.status = PunishmentStatus.ACTIVE
            punishment.second_confirmed_at = now
            punishment.expires_at = now + duration if duration is not None else None
            await session.flush()
            await session.refresh(punishment)
        return punishment

    async def cancel_pending(
        self,
        *,
        punishment_id: uuid.UUID,
        staff: discord.Member,
        reason: str = "Cancelado pela staff antes da aplicação.",
    ) -> Punishment:
        """Cancela uma punicao ainda nao aplicada (PENDING/NOTIFIED) — por cancelamento
        manual da staff ou porque a aplicacao falhou na Etapa 5 (ex.: bot sem permissao).
        Mantem o registro pra auditoria, so marca como REVOKED sem nunca ter sido aplicada
        de fato no Discord. Libera o usuario pro anti-duplicacao de um novo /punir."""
        async with self._database.session() as session:
            punishment = await PunishmentRepository(session).get_by_id(punishment_id)
            if punishment is None:
                raise PunishmentError("Punição não encontrada.")
            if punishment.guild_id != staff.guild.id:
                raise PunishmentError("Punição não encontrada.")
            if punishment.status not in UNRESOLVED_STATUSES:
                raise PunishmentError("Essa punição já foi processada (não está mais pendente).")
            punishment.status = PunishmentStatus.REVOKED
            punishment.revoked_by_id = staff.id
            punishment.revoked_by_name = str(staff)
            punishment.revoke_reason = reason
            punishment.revoked_at = datetime.now(UTC)
            await session.flush()
            await session.refresh(punishment)
        return punishment

    async def get_by_code(self, guild_id: int, code: str) -> Punishment | None:
        async with self._database.session() as session:
            return await PunishmentRepository(session).get_by_code(guild_id, code)

    async def get_by_id(self, punishment_id: uuid.UUID) -> Punishment | None:
        async with self._database.session() as session:
            return await PunishmentRepository(session).get_by_id(punishment_id)

    async def find_by_code(self, code: str) -> Punishment | None:
        """Busca por punishment_code sem exigir guild_id — usado no fallback de recurso
        por DM, onde o bot so tem o codigo digitado pelo usuario banido."""
        async with self._database.session() as session:
            return await PunishmentRepository(session).get_by_code_global(code)

    async def list_history(self, guild_id: int, user_id: int) -> list[Punishment]:
        async with self._database.session() as session:
            return await PunishmentRepository(session).list_by_user(guild_id, user_id)

    async def _lift_discord_action(
        self, guild: discord.Guild, punishment: Punishment, reason: str
    ) -> None:
        try:
            if punishment.type in (PunishmentType.BAN, PunishmentType.BAN_TEMPORARIO):
                await guild.unban(discord.Object(id=punishment.user_id), reason=reason)
            elif punishment.type == PunishmentType.TIMEOUT:
                member = guild.get_member(punishment.user_id)
                if member is not None:
                    await member.timeout(None, reason=reason)
        except discord.NotFound:
            pass
        except discord.Forbidden as exc:
            raise PunishmentError("O bot não tem permissão para reverter essa punição.") from exc
        except discord.HTTPException as exc:
            logger.exception("Falha na API do Discord ao revogar a punicao.")
            raise PunishmentError("Falha na API do Discord ao revogar a punição.") from exc

    async def revoke(
        self, *, guild: discord.Guild, punishment_id: uuid.UUID, revoked_by: discord.Member, reason: str
    ) -> Punishment:
        async with self._database.session() as session:
            punishment = await PunishmentRepository(session).get_by_id(punishment_id)
            if punishment is None:
                raise PunishmentError("Punição não encontrada.")
            if punishment.guild_id != guild.id:
                raise PunishmentError("Punição não encontrada.")
            if punishment.status == PunishmentStatus.REVOKED:
                raise PunishmentError("Essa punição já foi revogada.")

            # PENDING/NOTIFIED nunca chegaram a ser aplicadas no Discord (ex.: falha de
            # permissao na Etapa 5) — so precisa liberar o registro, sem tentar reverter
            # uma acao que nunca aconteceu.
            if punishment.status == PunishmentStatus.ACTIVE:
                await self._lift_discord_action(guild, punishment, reason)

            punishment.status = PunishmentStatus.REVOKED
            punishment.revoked_by_id = revoked_by.id
            punishment.revoked_by_name = str(revoked_by)
            punishment.revoke_reason = reason
            punishment.revoked_at = datetime.now(UTC)
            await session.flush()
            await session.refresh(punishment)
        return punishment

    async def restore_player_role_on_rejoin(
        self, *, member: discord.Member, player_role_id: int | None
    ) -> None:
        """Devolve o cargo de jogador quando o usuario reentra no servidor apos ter tido
        qualquer punicao revogada — ban/ban_temporario/kick tiram o membro da guild, entao
        nao ha como restaurar cargos na hora da revogacao (ele so volta a existir como
        member no rejoin)."""
        if player_role_id is None:
            return
        async with self._database.session() as session:
            has_revoked_punishment = await PunishmentRepository(session).has_revoked_punishment(
                member.guild.id, member.id
            )
        if not has_revoked_punishment:
            return
        role = member.guild.get_role(player_role_id)
        if role is None or role in member.roles:
            return
        with suppress(discord.HTTPException):
            await member.add_roles(role, reason="Cargo de jogador restaurado após ban revogado")

    async def submit_appeal(
        self,
        *,
        punishment_id: uuid.UUID,
        user_id: int,
        message: str,
        additional_info: str | None,
        method: AppealMethod = AppealMethod.BUTTON,
    ) -> PunishmentAppeal:
        async with self._database.session() as session:
            punishment = await PunishmentRepository(session).get_by_id(punishment_id)
            if punishment is None:
                raise AppealError("Punição não encontrada.")
            if punishment.user_id != user_id:
                raise AppealError("Você não pode recorrer da punição de outra pessoa.")
            if punishment.status == PunishmentStatus.REVOKED:
                raise AppealError("Essa punição já foi revogada.")
            if punishment.status == PunishmentStatus.EXPIRED:
                raise AppealError("Essa punição não permite recurso.")
            if punishment.status in UNRESOLVED_STATUSES:
                raise AppealError("Essa punição ainda não foi aplicada.")

            appeal_repo = PunishmentAppealRepository(session)
            if await appeal_repo.has_appeal(punishment_id):
                raise AppealError(
                    "Você já enviou um recurso para essa punição. Não é possível enviar outro."
                )

            appeal = await appeal_repo.add(
                PunishmentAppeal(
                    punishment_id=punishment_id,
                    user_id=user_id,
                    message=message,
                    additional_info=additional_info,
                    status=AppealStatus.PENDING,
                    method=method,
                )
            )
            await session.flush()
            await session.refresh(appeal)
        return appeal

    async def set_appeal_channel_message(self, appeal_id: uuid.UUID, message_id: int) -> None:
        async with self._database.session() as session:
            appeal = await PunishmentAppealRepository(session).get_by_id(appeal_id)
            if appeal is not None:
                appeal.channel_message_id = message_id

    async def get_appeal(self, appeal_id: uuid.UUID) -> PunishmentAppeal | None:
        async with self._database.session() as session:
            return await PunishmentAppealRepository(session).get_by_id(appeal_id)

    async def get_pending_appeal(self, punishment_id: uuid.UUID) -> PunishmentAppeal | None:
        async with self._database.session() as session:
            return await PunishmentAppealRepository(session).get_pending_by_punishment(punishment_id)

    async def map_pending_appeals(
        self, punishment_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, PunishmentAppeal]:
        """Batch de get_pending_appeal — 1 query pra N punicoes em vez de N
        queries (ver PunishmentAppealRepository.map_pending_by_punishments)."""
        async with self._database.session() as session:
            return await PunishmentAppealRepository(session).map_pending_by_punishments(punishment_ids)

    async def accept_appeal(
        self,
        *,
        guild: discord.Guild,
        appeal_id: uuid.UUID,
        reviewer: discord.Member,
        review_role_id: int | None = None,
        bypass_self_review: bool = False,
    ) -> AppealDecisionResult:
        async with self._database.session() as session:
            appeal = await PunishmentAppealRepository(session).get_by_id(appeal_id)
            if appeal is None:
                raise AppealError("Recurso não encontrado.")
            if appeal.status != AppealStatus.PENDING:
                raise AppealError("Esse recurso já foi analisado.")
            punishment = await PunishmentRepository(session).get_by_id(appeal.punishment_id)
            if punishment is None or punishment.guild_id != guild.id:
                raise AppealError("Punição associada não encontrada.")
            if punishment.staff_id == reviewer.id and not bypass_self_review:
                raise AppealError("Você não pode analisar o recurso da sua própria punição.")

            if punishment.status == PunishmentStatus.PENDING_REVIEW:
                await self._restore_review_roles(
                    session,
                    guild=guild,
                    punishment_id=punishment.id,
                    user_id=punishment.user_id,
                    review_role_id=review_role_id,
                )
            else:
                await self._lift_discord_action(guild, punishment, "Recurso de punição aceito")

            punishment.status = PunishmentStatus.REVOKED
            punishment.revoked_by_id = reviewer.id
            punishment.revoked_by_name = str(reviewer)
            punishment.revoke_reason = "Recurso aceito"
            punishment.revoked_at = datetime.now(UTC)

            appeal.status = AppealStatus.APPROVED
            appeal.reviewed_by_id = reviewer.id
            appeal.reviewed_by_name = str(reviewer)

            await session.flush()
            await session.refresh(punishment)
            await session.refresh(appeal)
        return AppealDecisionResult(punishment=punishment, appeal=appeal)

    async def deny_appeal(
        self,
        *,
        guild: discord.Guild,
        appeal_id: uuid.UUID,
        reviewer: discord.Member,
        reason: str,
        review_role_id: int | None = None,
        bypass_self_review: bool = False,
    ) -> AppealDecisionResult:
        async with self._database.session() as session:
            appeal = await PunishmentAppealRepository(session).get_by_id(appeal_id)
            if appeal is None:
                raise AppealError("Recurso não encontrado.")
            if appeal.status != AppealStatus.PENDING:
                raise AppealError("Esse recurso já foi analisado.")
            punishment = await PunishmentRepository(session).get_by_id(appeal.punishment_id)
            if punishment is None or punishment.guild_id != guild.id:
                raise AppealError("Punição associada não encontrada.")
            if punishment.staff_id == reviewer.id and not bypass_self_review:
                raise AppealError("Você não pode analisar o recurso da sua própria punição.")

            if punishment.status == PunishmentStatus.PENDING_REVIEW:
                await self._restore_review_roles(
                    session,
                    guild=guild,
                    punishment_id=punishment.id,
                    user_id=punishment.user_id,
                    review_role_id=review_role_id,
                )
                member = guild.get_member(punishment.user_id)
                duration = (
                    timedelta(seconds=punishment.duration_seconds)
                    if punishment.duration_seconds
                    else None
                )
                try:
                    if punishment.type in (PunishmentType.BAN, PunishmentType.BAN_TEMPORARIO):
                        target = member or discord.Object(id=punishment.user_id)
                        await guild.ban(target, reason=punishment.reason, delete_message_seconds=0)
                    elif punishment.type == PunishmentType.KICK and member is not None:
                        await guild.kick(member, reason=punishment.reason)
                    elif punishment.type == PunishmentType.TIMEOUT and member is not None:
                        await member.timeout(duration, reason=punishment.reason)
                except discord.Forbidden as exc:
                    raise AppealError(
                        "O bot não tem permissão para aplicar essa punição neste membro."
                    ) from exc
                except discord.HTTPException as exc:
                    logger.exception("Falha na API do Discord ao aplicar a punicao (recurso negado).")
                    raise AppealError("Falha na API do Discord ao aplicar a punição.") from exc

                now = datetime.now(UTC)
                punishment.status = PunishmentStatus.ACTIVE
                punishment.second_confirmed_at = now
                punishment.expires_at = now + duration if duration is not None else None

            appeal.status = AppealStatus.DENIED
            appeal.reviewed_by_id = reviewer.id
            appeal.reviewed_by_name = str(reviewer)
            appeal.review_reason = reason

            await session.flush()
            await session.refresh(punishment)
            await session.refresh(appeal)
        return AppealDecisionResult(punishment=punishment, appeal=appeal)
