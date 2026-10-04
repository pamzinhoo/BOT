from __future__ import annotations

import asyncio
import re
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta

import discord
from sqlalchemy import and_, func, or_, select, union_all, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError

from core.logger import get_logger
from core.rate_limiter import RateLimiter, RateLimitExceeded
from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.base import Base
from database.models.redemption import Redemption, RedemptionCode, RedemptionRoleGrant
from database.repositories.redemption_repository import RedemptionRepository

logger = get_logger("redemption_service")
LEASE_SECONDS = 90
MAX_ATTEMPTS = 5
CODE_FIELDS = (
    "code",
    "reward_type",
    "role_id",
    "role_duration_seconds",
    "temporary_role_ack",
    "message",
    "delivery",
    "starts_at",
    "expires_at",
    "max_uses",
    "active",
)


class RedemptionError(ValueError):
    """Validation failures safe to display in a private response."""


def normalize_code(value: str) -> str:
    value = value.strip()
    # Validate ASCII before uppercase: Unicode case folding must not create valid codes.
    if (
        not re.fullmatch(r"[A-Za-z0-9]{8}", value)
        or not re.search(r"[A-Za-z]", value)
        or not re.search(r"[0-9]", value)
    ):
        raise RedemptionError("Use exatamente 8 caracteres, incluindo letras e números.")
    return value.upper()


def generate_code() -> str:
    while True:
        code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        if re.search(r"[A-Z]", code) and re.search(r"[0-9]", code):
            return code


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _json(value):
    if isinstance(value, datetime):
        return utc(value).isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


class RedemptionService:
    def __init__(self, database: Database, bot=None) -> None:
        self._database = database
        self._bot = bot
        self._users = RateLimiter(max_hits=5, window_seconds=60)
        self._guilds = RateLimiter(max_hits=100, window_seconds=60)
        self._network = asyncio.Semaphore(4)

    generate_code = staticmethod(generate_code)

    @staticmethod
    def _validate(fields: dict) -> dict:
        data = {
            "reward_type": "message",
            "role_id": None,
            "role_duration_seconds": None,
            "temporary_role_ack": False,
            "message": "Código resgatado com sucesso!",
            "delivery": "channel",
            "starts_at": None,
            "expires_at": None,
            "max_uses": None,
            "active": True,
            **fields,
        }
        if set(data) - set(CODE_FIELDS):
            raise RedemptionError("Configuração de resgate desconhecida.")
        data["code"] = normalize_code(data["code"])
        if data["reward_type"] not in ("message", "role") or data["delivery"] not in (
            "channel",
            "dm",
        ):
            raise RedemptionError("Recompensa ou destino inválido.")
        if (
            not isinstance(data["message"], str)
            or not data["message"].strip()
            or len(data["message"]) > 1800
        ):
            raise RedemptionError("A mensagem deve ter entre 1 e 1800 caracteres.")
        expanded = (
            data["message"]
            .replace("{usuario}", "<@1234567890123456789>")
            .replace(
                "{cargo}",
                "<@&1234567890123456789>",
            )
            .replace("{duracao}", "315360000 segundos")
        )
        if len(expanded) > 2000:
            raise RedemptionError(
                "Reduza a mensagem: os campos substituídos excedem 2000 caracteres."
            )
        for key in ("active", "temporary_role_ack"):
            if not isinstance(data[key], bool):
                raise RedemptionError("Opção inválida.")
        for key, maximum in (
            ("role_id", 2**63 - 1),
            ("max_uses", 2**31 - 1),
            ("role_duration_seconds", 315360000),
        ):
            value = data[key]
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum
            ):
                raise RedemptionError(
                    "Cargo, limite e duração devem ser números positivos válidos."
                )
        if data["reward_type"] == "role" and data["role_id"] is None:
            raise RedemptionError("Selecione o cargo da recompensa.")
        if data["reward_type"] == "message" and (
            data["role_id"] is not None or data["role_duration_seconds"] is not None
        ):
            raise RedemptionError("Recompensa de mensagem não pode configurar cargo.")
        if data["role_duration_seconds"] is not None and not data["temporary_role_ack"]:
            raise RedemptionError("Confirme a proteção na expiração do cargo temporário.")
        for key in ("starts_at", "expires_at"):
            if data[key] is not None:
                if not isinstance(data[key], datetime):
                    raise RedemptionError("Data inválida.")
                data[key] = utc(data[key])
        if data["starts_at"] and data["expires_at"] and data["starts_at"] >= data["expires_at"]:
            raise RedemptionError("O vencimento deve ser posterior ao início.")
        return data

    @staticmethod
    def _code_dict(code: RedemptionCode, uses: int = 0) -> dict:
        result = {field: _json(getattr(code, field)) for field in CODE_FIELDS}
        result.update(
            id=str(code.id),
            guild_id=str(code.guild_id),
            uses=uses,
            created_at=_json(code.created_at),
            updated_at=_json(code.updated_at),
        )
        result["role_id"] = str(code.role_id) if code.role_id else None
        return result

    async def list_codes(self, guild_id: int) -> list[dict]:
        async with self._database.session() as session:
            counts = (
                select(Redemption.code_id, func.count().label("uses"))
                .where(
                    Redemption.guild_id == guild_id,
                    Redemption.status != "failed",
                )
                .group_by(Redemption.code_id)
                .subquery()
            )
            rows = (
                await session.execute(
                    select(RedemptionCode, func.coalesce(counts.c.uses, 0))
                    .outerjoin(
                        counts,
                        counts.c.code_id == RedemptionCode.id,
                    )
                    .where(RedemptionCode.guild_id == guild_id)
                    .order_by(RedemptionCode.created_at.desc())
                )
            ).all()
            return [self._code_dict(code, count) for code, count in rows]

    async def create_code(self, guild_id: int, **fields) -> dict:
        automatic = not fields.get("code")
        for _ in range(5):
            data = self._validate(
                {**fields, "code": generate_code() if automatic else fields["code"]}
            )
            await self._validate_config_role(guild_id, data)
            try:
                async with self._database.session() as session:
                    code = RedemptionCode(guild_id=guild_id, **data)
                    session.add(code)
                    await session.flush()
                    result = self._code_dict(code)
                await self._audit(guild_id, "Código de resgate criado", code_id=str(code.id))
                await self._refresh_shop_panel(guild_id)
                return result
            except IntegrityError as exc:
                if not automatic:
                    raise RedemptionError("Este código já existe neste servidor.") from exc
        raise RedemptionError("Não foi possível gerar um código livre. Tente novamente.")

    async def update_code(self, guild_id: int, code_id: uuid.UUID, **fields) -> dict:
        # Read once for external validation; revalidate merged data under lock before saving.
        async with self._database.session() as session:
            current = await RedemptionRepository(session).code(guild_id, code_id=code_id)
            if current is None:
                raise RedemptionError("Código não encontrado neste servidor.")
            version = current.updated_at
            data = self._validate({**{key: getattr(current, key) for key in CODE_FIELDS}, **fields})
        if not (set(fields) == {"active"} and fields["active"] is False):
            await self._validate_config_role(guild_id, data)
        async with self._database.session() as session:
            repo = RedemptionRepository(session)
            code = await repo.code(guild_id, code_id=code_id, lock=True)
            if code is None:
                raise RedemptionError("Código não encontrado neste servidor.")
            if code.updated_at != version:
                raise RedemptionError(
                    "Este código foi alterado por outra operação. Atualize a página e tente novamente."
                )
            # Only write the already-validated complete snapshot; no unchecked merged values.
            if data["code"] != code.code:
                raise RedemptionError("O código não pode ser alterado; crie outro código.")
            uses = await repo.uses(guild_id, code_id)
            if data["max_uses"] is not None and data["max_uses"] < uses:
                raise RedemptionError("O limite não pode ser menor que os usos já reservados.")
            for key, value in data.items():
                setattr(code, key, value)
            await session.flush()
            result = self._code_dict(code, uses)
        await self._audit(guild_id, "Código de resgate atualizado", code_id=str(code_id))
        return result

    async def history(self, guild_id: int, code_id: uuid.UUID, *, limit: int = 50) -> list[dict]:
        async with self._database.session() as session:
            if await RedemptionRepository(session).code(guild_id, code_id=code_id) is None:
                raise RedemptionError("Código não encontrado neste servidor.")
            rows = (
                await session.execute(
                    select(Redemption, RedemptionRoleGrant)
                    .outerjoin(
                        RedemptionRoleGrant,
                        and_(
                            RedemptionRoleGrant.id == Redemption.grant_id,
                            RedemptionRoleGrant.guild_id == guild_id,
                        ),
                    )
                    .where(
                        Redemption.guild_id == guild_id,
                        Redemption.code_id == code_id,
                    )
                    .order_by(Redemption.created_at.desc())
                    .limit(max(1, min(limit, 100)))
                )
            ).all()
            return [
                {
                    field: _json(getattr(row, field))
                    for field in (
                        "id",
                        "status",
                        "error",
                        "created_at",
                        "delivered_at",
                        "role_expires_at",
                        "notification_status",
                    )
                }
                | {
                    "user_id": str(row.user_id),
                    "role_status": grant.status if grant else None,
                    "role_error": grant.error if grant else None,
                }
                for row, grant in rows
            ]

    async def _validate_config_role(self, guild_id: int, data: dict) -> None:
        if data["reward_type"] == "role":
            guild = self._bot.get_guild(guild_id) if self._bot else None
            if guild is None:
                raise RedemptionError("Servidor indisponível para validar o cargo.")
            await self.validate_role(
                guild, data["role_id"], temporary=data["role_duration_seconds"] is not None
            )

    async def validate_role(self, guild, role_id: int, *, temporary: bool = False):
        role = guild.get_role(role_id)
        me = guild.me
        if role is None or role.id == guild.id or role.managed:
            raise RedemptionError("Cargo inválido ou gerenciado pelo Discord.")
        if me is None or not me.guild_permissions.manage_roles or role >= me.top_role:
            raise RedemptionError(
                "O bot precisa gerenciar cargos e estar acima do cargo escolhido."
            )
        if any(
            getattr(role.permissions, name, False)
            for name in (
                "administrator",
                "manage_guild",
                "manage_roles",
                "manage_channels",
                "manage_webhooks",
                "ban_members",
                "kick_members",
                "moderate_members",
                "manage_messages",
                "mention_everyone",
            )
        ):
            raise RedemptionError(
                "Cargos com permissões administrativas não podem ser recompensas."
            )
        if temporary and not me.guild_permissions.view_audit_log:
            raise RedemptionError(
                "Cargos temporários exigem a permissão Ver registro de auditoria para remoção segura."
            )
        return role

    async def _shared_role(self, guild_id: int, role_id: int) -> bool:
        queries = []
        # Existing metadata covers every configured scalar/list role, including permissions.
        for table in Base.metadata.tables.values():
            if (
                table.name.startswith("redemption")
                or table.name == "channel_guard_incidents"
                or "guild_id" not in table.c
            ):
                continue
            conditions = []
            for column in table.c:
                if column.name.endswith("role_id"):
                    conditions.append(column == role_id)
                elif isinstance(column.type, JSONB) and (
                    column.name.endswith("role_ids") or table.name == "permission_settings"
                ):
                    conditions.append(
                        or_(column.contains([role_id]), column.contains([str(role_id)]))
                    )
            if conditions:
                queries.append(
                    select(table.c.guild_id).where(table.c.guild_id == guild_id, or_(*conditions))
                )
        if not queries:
            return False
        async with self._database.session() as session:
            return (await session.execute(union_all(*queries).limit(1))).first() is not None

    async def _reserve(
        self, guild_id: int, user_id: int, code: str, *, member_has_role: bool = False
    ) -> Redemption:
        normalized = normalize_code(code)
        now = datetime.now(UTC)
        async with self._database.session() as session:
            repo = RedemptionRepository(session)
            campaign = await repo.code(guild_id, code=normalized, lock=True)
            if campaign is None:
                raise RedemptionError("Código inválido neste servidor.")
            existing = await repo.user_redemption(guild_id, campaign.id, user_id)
            if existing is not None:
                return existing
            if not campaign.active:
                raise RedemptionError("Este código está desativado.")
            if campaign.starts_at and utc(campaign.starts_at) > now:
                raise RedemptionError("Este código ainda não está disponível.")
            if campaign.expires_at and utc(campaign.expires_at) <= now:
                raise RedemptionError("Este código expirou.")
            if (
                campaign.max_uses is not None
                and await repo.uses(guild_id, campaign.id) >= campaign.max_uses
            ):
                raise RedemptionError("Este código atingiu o limite de resgates.")
            grant = None
            if campaign.reward_type == "role":
                grant = await repo.member_grant(guild_id, user_id, campaign.role_id)
                if grant.status == "suspended":
                    raise RedemptionError("Este cargo aguarda revisão da equipe.")
                if (
                    campaign.role_duration_seconds is not None
                    and member_has_role
                    and not grant.owns_role
                ):
                    raise RedemptionError("Você já possui este cargo. Nenhum uso foi consumido.")
                inflight = (
                    await session.execute(
                        select(Redemption.id)
                        .where(
                            Redemption.guild_id == guild_id,
                            Redemption.grant_id == grant.id,
                            Redemption.status.in_(("pending", "uncertain")),
                        )
                        .limit(1)
                    )
                ).first()
                if inflight:
                    raise RedemptionError(
                        "Outro resgate deste cargo aguarda confirmação. Tente novamente depois."
                    )
            message = (
                campaign.message.replace("{usuario}", f"<@{user_id}>")
                .replace(
                    "{cargo}",
                    f"<@&{campaign.role_id}>" if campaign.role_id else "",
                )
                .replace(
                    "{duracao}",
                    f"{campaign.role_duration_seconds} segundos"
                    if campaign.role_duration_seconds
                    else "permanente",
                )
            )
            redemption = Redemption(
                guild_id=guild_id,
                code_id=campaign.id,
                user_id=user_id,
                grant_id=grant.id if grant else None,
                reward_type=campaign.reward_type,
                role_id=campaign.role_id,
                role_duration_seconds=campaign.role_duration_seconds,
                message=message,
                delivery=campaign.delivery,
                status="pending",
                next_attempt_at=now,
            )
            session.add(redemption)
            await session.flush()
            return redemption

    async def redeem(self, guild, member, code: str) -> dict:
        if member.guild.id != guild.id or member.bot:
            raise RedemptionError("Resgate disponível somente para membros deste servidor.")
        try:
            await self._users.hit(f"{guild.id}:{member.id}")
            await self._guilds.hit(str(guild.id))
        except RateLimitExceeded as exc:
            raise RedemptionError(
                "Muitas tentativas. Aguarde um minuto e tente novamente."
            ) from exc
        # A fresh member query prevents accepting a manually-held temporary role from stale cache.
        async with self._database.session() as session:
            campaign = await RedemptionRepository(session).code(guild.id, code=normalize_code(code))
            existing = (
                await RedemptionRepository(session).user_redemption(
                    guild.id, campaign.id, member.id
                )
                if campaign
                else None
            )
        if campaign is None:
            raise RedemptionError("Código inválido neste servidor.")
        has_role = False
        if existing is None and campaign.reward_type == "role":
            await self.validate_role(
                guild, campaign.role_id, temporary=campaign.role_duration_seconds is not None
            )
            async with asyncio.timeout(20):
                member = await guild.fetch_member(member.id)
            has_role = any(role.id == campaign.role_id for role in member.roles)
        row = await self._reserve(guild.id, member.id, code, member_has_role=has_role)
        if row.status == "pending":
            await self._deliver(guild, row.id)
        async with self._database.session() as session:
            row = await RedemptionRepository(session).redemption(guild.id, row.id)
            return self._result(row)

    @staticmethod
    def _result(row: Redemption) -> dict:
        message = (
            row.message
            if row.status == "delivered"
            else {
                "pending": "Resgate em processamento. Tente o mesmo código novamente para consultar a recompensa.",
                "failed": "A recompensa não pôde ser entregue. Procure a equipe.",
                "uncertain": "A entrega aguarda verificação da equipe. Não tente outro resgate para repetir a recompensa.",
            }.get(row.status, "Resgate já registrado.")
        )
        return dict(
            id=str(row.id),
            guild_id=str(row.guild_id),
            user_id=str(row.user_id),
            status=row.status,
            message=message,
            delivery=row.delivery,
            notification_status=row.notification_status,
        )

    async def claim_notification(self, guild_id: int, redemption_id: uuid.UUID) -> bool:
        async with self._database.session() as session:
            result = await session.execute(
                update(Redemption)
                .where(
                    Redemption.guild_id == guild_id,
                    Redemption.id == redemption_id,
                    Redemption.status == "delivered",
                    Redemption.notification_status == "pending",
                )
                .values(notification_status="sending", updated_at=datetime.now(UTC))
                .returning(Redemption.id)
            )
            return result.scalar_one_or_none() is not None

    async def complete_notification(
        self, guild_id: int, redemption_id: uuid.UUID, status: str
    ) -> None:
        if status not in ("sent", "uncertain"):
            raise ValueError("Invalid notification status")
        async with self._database.session() as session:
            await session.execute(
                update(Redemption)
                .where(
                    Redemption.guild_id == guild_id,
                    Redemption.id == redemption_id,
                    Redemption.notification_status == "sending",
                )
                .values(notification_status=status)
            )

    async def _claim_delivery(self, guild_id: int, redemption_id: uuid.UUID):
        now = datetime.now(UTC)
        async with self._database.session() as session:
            repo = RedemptionRepository(session)
            row = await repo.redemption(guild_id, redemption_id, lock=True)
            if (
                row is None
                or row.status != "pending"
                or (row.next_attempt_at and utc(row.next_attempt_at) > now)
            ):
                return None
            if row.reward_type == "message":
                row.status = "delivered"
                row.delivered_at = now
                return row, None
            grant = await repo.grant(guild_id, row.grant_id, lock=True)
            if grant.status == "suspended":
                row.status, row.error = "uncertain", "Cargo suspenso; revisão necessária."
                return None
            if grant.lease_until and utc(grant.lease_until) > now:
                return None
            if grant.status == "removed":
                grant.owns_role = False
                grant.origin_redemption_id = None
                grant.permanent = False
                grant.expires_at = None
            grant.lease_token = uuid.uuid4()
            grant.lease_until = now + timedelta(seconds=LEASE_SECONDS)
            if not grant.owns_role:
                grant.origin_redemption_id = row.id
                grant.granted_at = now
            row.next_attempt_at = grant.lease_until
            row.attempts += 1
            await session.flush()
            return row, grant

    async def _deliver(self, guild, redemption_id: uuid.UUID) -> None:
        # Each Discord operation has a timeout shorter than the durable lease.
        async with self._network:
            claimed = await self._claim_delivery(guild.id, redemption_id)
            if claimed is None:
                return
            row, grant = claimed
            if grant is None:
                await self._audit(
                    row.guild_id,
                    "Recompensa de resgate entregue",
                    redemption_id=str(row.id),
                    user_id=str(row.user_id),
                )
                return
            try:
                async with asyncio.timeout(25):
                    role = await self.validate_role(
                        guild, row.role_id, temporary=row.role_duration_seconds is not None
                    )
                    member = await guild.fetch_member(row.user_id)
                    has_role = any(item.id == role.id for item in member.roles)
                    if grant.owns_role and not has_role:
                        await self._delivery_failure(
                            row,
                            grant,
                            "Cargo removido externamente; revisão necessária.",
                            uncertain=True,
                            suspend=True,
                        )
                        return
                    owns_role = grant.owns_role
                    if has_role and row.role_duration_seconds is not None:
                        if not await self._ownership_proven(guild, grant):
                            # A manually-held role is never adopted for later removal.
                            await self._delivery_failure(
                                row,
                                grant,
                                "Origem do cargo não comprovada; revisão necessária.",
                                uncertain=True,
                                suspend=True,
                            )
                            return
                        owns_role = True
                    if not has_role:
                        await member.add_roles(
                            role, reason=f"redemption:{grant.origin_redemption_id}"
                        )
                        owns_role = True
                await self._finish_delivery(row, grant, owns_role=owns_role)
            except (discord.Forbidden, discord.NotFound, RedemptionError) as exc:
                await self._delivery_failure(
                    row,
                    grant,
                    str(exc) if isinstance(exc, RedemptionError) else "Discord recusou a entrega.",
                    definitive=True,
                )
            except Exception:
                # Network timeouts and commit failures can follow a successful Discord PUT.
                # Keep the reservation; the next attempt verifies member roles before any PUT.
                logger.warning("Entrega de resgate pendente: %s", row.id, exc_info=True)
                await self._delivery_failure(
                    row, grant, "Entrega não confirmada; nova verificação agendada."
                )

    async def _finish_delivery(
        self, row: Redemption, claimed_grant: RedemptionRoleGrant, *, owns_role: bool
    ) -> None:
        now = datetime.now(UTC)
        async with self._database.session() as session:
            repo = RedemptionRepository(session)
            current = await repo.redemption(row.guild_id, row.id, lock=True)
            grant = await repo.grant(row.guild_id, row.grant_id, lock=True)
            if current.status != "pending" or grant.lease_token != claimed_grant.lease_token:
                return
            current.status = "delivered"
            current.delivered_at = now
            current.error = None
            current.role_expires_at = (
                now + timedelta(seconds=row.role_duration_seconds)
                if row.role_duration_seconds
                else None
            )
            grant.owns_role = owns_role
            grant.permanent = grant.permanent or row.role_duration_seconds is None
            if current.role_expires_at:
                grant.expires_at = (
                    max(utc(grant.expires_at), current.role_expires_at)
                    if grant.expires_at
                    else current.role_expires_at
                )
            grant.status = "active"
            grant.attempts = 0
            grant.error = None
            grant.lease_until = None
            grant.lease_token = None
        await self._audit(
            row.guild_id,
            "Recompensa de resgate entregue",
            redemption_id=str(row.id),
            user_id=str(row.user_id),
        )

    async def _delivery_failure(
        self,
        row: Redemption,
        claimed_grant: RedemptionRoleGrant,
        error: str,
        *,
        definitive: bool = False,
        uncertain: bool = False,
        suspend: bool = False,
    ) -> None:
        async with self._database.session() as session:
            repo = RedemptionRepository(session)
            current = await repo.redemption(row.guild_id, row.id, lock=True)
            grant = await repo.grant(row.guild_id, row.grant_id, lock=True)
            if current.status != "pending" or grant.lease_token != claimed_grant.lease_token:
                return
            # A later definite refusal cannot erase a previous ambiguous PUT.
            if definitive and current.attempts == 1:
                current.status = "failed"
            elif uncertain or current.attempts >= MAX_ATTEMPTS or definitive:
                current.status = "uncertain"
            current.error = error[:300]
            current.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=min(3600, 60 * 2**current.attempts)
            )
            grant.lease_until = None
            grant.lease_token = None
            if suspend:
                grant.status, grant.error = "suspended", current.error
        await self._audit(
            row.guild_id,
            "Entrega de resgate pendente",
            redemption_id=str(row.id),
            user_id=str(row.user_id),
            error=error[:300],
        )

    async def _ownership_proven(self, guild, grant: RedemptionRoleGrant) -> bool:
        """Only the latest role change for this member can prove our ownership.

        Discord does not expose an origin on Member.roles. Missing/expired audit
        records fail closed; never remove a role based only on the local snapshot.
        """
        async for entry in guild.audit_logs(
            limit=100, action=discord.AuditLogAction.member_role_update
        ):
            if getattr(entry.target, "id", None) != grant.user_id:
                continue
            before = getattr(entry.before, "roles", []) or []
            after = getattr(entry.after, "roles", []) or []
            if not any(role.id == grant.role_id for role in (*before, *after)):
                continue
            return (
                getattr(entry.user, "id", None) == guild.me.id
                and entry.reason == f"redemption:{grant.origin_redemption_id}"
                and any(role.id == grant.role_id for role in after)
            )
        return False

    async def process_pending(self, bot=None) -> None:
        bot = bot or self._bot
        if bot is None:
            return
        now = datetime.now(UTC)
        guild_ids = [guild.id for guild in bot.guilds]
        async with self._database.session() as session:
            due = await RedemptionRepository(session).due(now, guild_ids=guild_ids)
            # A crash after sending a private message must never trigger blind resend.
            await session.execute(
                update(Redemption)
                .where(
                    Redemption.notification_status == "sending",
                    Redemption.updated_at < now - timedelta(seconds=LEASE_SECONDS),
                )
                .values(notification_status="uncertain")
            )
            grants = (
                await session.execute(
                    select(RedemptionRoleGrant.guild_id, RedemptionRoleGrant.id)
                    .where(
                        RedemptionRoleGrant.status.in_(("active", "removing")),
                        RedemptionRoleGrant.guild_id.in_(guild_ids),
                        RedemptionRoleGrant.permanent.is_(False),
                        RedemptionRoleGrant.expires_at <= now,
                        or_(
                            RedemptionRoleGrant.lease_until.is_(None),
                            RedemptionRoleGrant.lease_until <= now,
                        ),
                        ~select(Redemption.id)
                        .where(
                            Redemption.guild_id == RedemptionRoleGrant.guild_id,
                            Redemption.grant_id == RedemptionRoleGrant.id,
                            Redemption.status == "pending",
                        )
                        .exists(),
                    )
                    .order_by(RedemptionRoleGrant.expires_at)
                    .limit(25)
                )
            ).all()
            notifications = (
                await session.execute(
                    select(Redemption.guild_id, Redemption.id)
                    .where(
                        Redemption.guild_id.in_(guild_ids),
                        Redemption.status == "delivered",
                        Redemption.delivery == "dm",
                        Redemption.notification_status == "pending",
                        Redemption.updated_at < now - timedelta(seconds=LEASE_SECONDS),
                    )
                    .order_by(Redemption.updated_at)
                    .limit(25)
                )
            ).all()

        async def deliver_one(guild_id, redemption_id):
            guild = bot.get_guild(guild_id)
            if guild is None:
                return
            try:
                await self._deliver(guild, redemption_id)
            except Exception:
                logger.exception("Falha isolada ao recuperar resgate %s", redemption_id)

        async def expire_one(guild_id, grant_id):
            guild = bot.get_guild(guild_id)
            if guild is None:
                return
            try:
                await self._expire_grant(guild, grant_id)
            except Exception:
                logger.exception("Falha isolada ao expirar concessão %s", grant_id)

        async def notify_one(guild_id, redemption_id):
            guild = bot.get_guild(guild_id)
            if guild is None:
                return
            try:
                await self._recover_dm_notification(guild, redemption_id)
            except Exception:
                logger.exception("Falha isolada ao notificar resgate %s", redemption_id)

        await asyncio.gather(
            *(deliver_one(guild_id, row_id) for guild_id, row_id in due),
            *(expire_one(guild_id, grant_id) for guild_id, grant_id in grants),
            *(notify_one(guild_id, row_id) for guild_id, row_id in notifications),
        )

    async def _recover_dm_notification(self, guild, redemption_id: uuid.UUID) -> None:
        """Recover unsent DMs after restart; never replay an ambiguous send."""
        async with self._network:
            async with self._database.session() as session:
                row = await RedemptionRepository(session).redemption(guild.id, redemption_id)
            if row is None or row.delivery != "dm":
                return
            if not await self.claim_notification(guild.id, redemption_id):
                return
            try:
                async with asyncio.timeout(25):
                    member = await guild.fetch_member(row.user_id)
                    await member.send(row.message, allowed_mentions=discord.AllowedMentions.none())
            except (discord.Forbidden, discord.NotFound):
                # A definitive refusal permits private pickup through the shop later.
                async with self._database.session() as session:
                    await session.execute(
                        update(Redemption)
                        .where(
                            Redemption.guild_id == guild.id,
                            Redemption.id == redemption_id,
                            Redemption.notification_status == "sending",
                        )
                        .values(delivery="channel", notification_status="pending")
                    )
                await self._audit(
                    guild.id,
                    "Mensagem de resgate disponível na loja",
                    redemption_id=str(redemption_id),
                    user_id=str(row.user_id),
                )
                return
            except (discord.HTTPException, TimeoutError):
                await self.complete_notification(guild.id, redemption_id, "uncertain")
                return
            await self.complete_notification(guild.id, redemption_id, "sent")

    async def _expire_grant(self, guild, grant_id: uuid.UUID) -> None:
        # Acquire concurrency capacity before issuing a lease, not while it expires in a queue.
        async with self._network:
            await self._expire_grant_locked(guild, grant_id)

    async def _expire_grant_locked(self, guild, grant_id: uuid.UUID) -> None:
        now = datetime.now(UTC)
        async with self._database.session() as session:
            repo = RedemptionRepository(session)
            grant = await repo.grant(guild.id, grant_id, lock=True)
            if (
                grant is None
                or grant.status not in ("active", "removing")
                or grant.permanent
                or not grant.expires_at
                or utc(grant.expires_at) > now
            ):
                return
            if grant.lease_until and utc(grant.lease_until) > now:
                return
            pending = (
                await session.execute(
                    select(Redemption.status)
                    .where(
                        Redemption.guild_id == guild.id,
                        Redemption.grant_id == grant.id,
                        Redemption.status.in_(("pending", "uncertain")),
                    )
                    .limit(1)
                )
            ).first()
            if pending:
                if pending[0] == "uncertain":
                    grant.status = "suspended"
                    grant.error = "Existe uma entrega incerta deste cargo; revisão necessária."
                return
            if not grant.owns_role:
                grant.status = "suspended"
                grant.error = "Sem prova de concessão própria."
                return
            grant.status = "removing"
            grant.attempts += 1
            grant.lease_token = uuid.uuid4()
            grant.lease_until = now + timedelta(seconds=LEASE_SECONDS)
            await session.flush()
        outcome, error = "removed", None
        try:
            async with asyncio.timeout(25):
                role = await self.validate_role(guild, grant.role_id, temporary=True)
                member = await guild.fetch_member(grant.user_id)
                if any(item.id == role.id for item in member.roles):
                    if await self._shared_role(guild.id, grant.role_id):
                        outcome, error = (
                            "suspended",
                            "Cargo usado por outro recurso; preservado para evitar perda de acesso.",
                        )
                    elif not await self._ownership_proven(guild, grant):
                        outcome, error = (
                            "suspended",
                            "Cargo alterado externamente ou auditoria insuficiente.",
                        )
                    else:
                        await member.remove_roles(role, reason=f"redemption-expired:{grant.id}")
        except discord.NotFound:
            # A departed member or deleted role has no role left to revoke.
            pass
        except (RedemptionError, discord.Forbidden):
            outcome, error = (
                "suspended",
                "Proteção de cargo ou permissão alterada; revisão necessária.",
            )
        except Exception:
            # Retry the read after lease expiration; removal itself is idempotent.
            logger.exception("Remoção de concessão não confirmada: %s", grant.id)
            if grant.attempts < MAX_ATTEMPTS:
                return
            outcome, error = (
                "suspended",
                "Não foi possível confirmar a remoção após cinco tentativas.",
            )
        async with self._database.session() as session:
            current = await RedemptionRepository(session).grant(guild.id, grant.id, lock=True)
            if current.lease_token != grant.lease_token:
                return
            current.status, current.error = outcome, error
            current.lease_until = None
            current.lease_token = None
            if outcome == "removed":
                current.owns_role = False
        await self._audit(
            guild.id,
            "Cargo de resgate expirado" if outcome == "removed" else "Remoção de resgate suspensa",
            grant_id=str(grant.id),
            user_id=str(grant.user_id),
            error=error,
        )

    async def _refresh_shop_panel(self, guild_id: int) -> None:
        panel = getattr(self._bot, "painel_service", None)
        if panel is None:
            return
        try:
            async with asyncio.timeout(10):
                await panel.refresh_shop_panel(guild_id)
        except Exception:
            logger.exception(
                "Não foi possível atualizar o botão de resgate da loja: guild %s", guild_id
            )

    async def _audit(self, guild_id: int, action: str, **details) -> None:
        if self._bot is None:
            return
        try:
            user_id = int(details["user_id"]) if details.get("user_id") is not None else None
            guild = self._bot.get_guild(guild_id) if user_id is not None else None
            member = (
                guild.get_member(user_id)
                if guild is not None and hasattr(guild, "get_member")
                else None
            )
            name = getattr(member, "display_name", None)
            target_name = (
                f"{name} ({user_id})" if name else str(user_id) if user_id is not None else None
            )
            if user_id is not None:
                details = {"Usuário": target_name, **details}
            await self._bot.audit_log_service.record(
                guild_id=guild_id,
                category=AuditLogCategory.COUPON,
                action=action,
                target_id=user_id,
                target_name=target_name,
                details=details,
            )
        except Exception:
            logger.exception("Falha na auditoria de resgate: guild %s, ação %s", guild_id, action)
