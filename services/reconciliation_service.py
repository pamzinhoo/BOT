from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import discord

from core.logger import get_logger
from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.plan import Plan
from database.repositories.license_repository import LicenseRepository
from database.repositories.plan_repository import PlanRepository
from database.repositories.player_repository import PlayerRepository

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("reconciliation_service")


@dataclass
class GuildReconciliationResult:
    guild_id: int
    roles_granted: int = 0
    roles_removed: int = 0
    errors: int = 0


@dataclass
class ReconciliationReport:
    guilds_checked: int = 0
    roles_granted: int = 0
    roles_removed: int = 0
    errors: int = 0
    per_guild: list[GuildReconciliationResult] = field(default_factory=list)


class ReconciliationService:
    """Reconciliacao periodica entre License (backend, fonte de verdade) e
    cargo Discord (bot, reflexo) — a rede de seguranca da Fase 5: "Nunca
    confiar apenas em eventos do Discord". Eventos (RoleSyncService) cobrem o
    caminho feliz; isto cobre o resto — bot offline quando o evento disparou,
    membro que saiu e voltou (Discord zera cargo sozinho), falha de rede
    pontual, edicao manual de cargo por um staff. Corrige nas duas direcoes e
    audita cada correcao (nunca corrige em silencio)."""

    def __init__(self, database: Database, bot: LimerenceBot) -> None:
        self._database = database
        self._bot = bot
        # O ciclo periodico (LicenseReconciliationCog) e o endpoint sob
        # demanda (/internal/reconcile) chamam o mesmo metodo — sem trava,
        # dois disparos quase simultaneos rodariam duas reconciliacoes
        # completas em paralelo (duplicando idas ao banco/Discord e linhas
        # de auditoria). A trava so serializa: o segundo disparo espera o
        # primeiro terminar em vez de correr junto.
        self._lock = asyncio.Lock()

    async def reconcile_all_guilds(self) -> ReconciliationReport:
        async with self._lock:
            report = ReconciliationReport()
            results = await asyncio.gather(
                *(self.reconcile_guild(guild) for guild in self._bot.guilds),
                return_exceptions=True,
            )
            for guild, result in zip(self._bot.guilds, results):
                if isinstance(result, BaseException):
                    report.errors += 1
                    logger.exception(
                        "Falha ao reconciliar guild %s.", guild.id, exc_info=result
                    )
                    continue
                report.guilds_checked += 1
                report.roles_granted += result.roles_granted
                report.roles_removed += result.roles_removed
                report.errors += result.errors
                report.per_guild.append(result)
            return report

    async def reconcile_guild(self, guild: discord.Guild) -> GuildReconciliationResult:
        result = GuildReconciliationResult(guild_id=guild.id)
        async with self._database.session() as session:
            plans = await PlanRepository(session).list_by_guild(guild.id)
        plans = [p for p in plans if p.product_id is not None and p.role_id is not None]

        for plan in plans:
            try:
                await self._reconcile_plan(guild, plan, result)
            except Exception:
                result.errors += 1
                logger.exception(
                    "Falha ao reconciliar plano %s (produto %s) na guild %s.", plan.id, plan.product_id, guild.id
                )
        return result

    async def _reconcile_plan(self, guild: discord.Guild, plan: Plan, result: GuildReconciliationResult) -> None:
        role = guild.get_role(plan.role_id)  # type: ignore[arg-type]
        if role is None:
            return
        product_id: uuid.UUID = plan.product_id  # type: ignore[assignment]

        role_members = list(role.members)

        async with self._database.session() as session:
            player_repo = PlayerRepository(session)
            license_repo = LicenseRepository(session)

            # direcao 1: tem cargo no Discord, mas License nao esta ACTIVE
            # (revogada/expirada sem o evento ter sido processado, ou cargo
            # dado manualmente por um staff sem compra correspondente).
            # Batelado (2 queries no total, nao 2*N) pra evitar N+1: resolve
            # todo Player dos membros do cargo de uma vez, depois toda
            # License ativa desses players pro product de uma vez.
            players_by_discord_id = {
                p.discord_id: p for p in await player_repo.list_by_discord_ids([m.id for m in role_members])
            }
            player_ids_with_role = [p.id for p in players_by_discord_id.values()]
            player_ids_with_active_license = {
                license_row.player_id
                for license_row in await license_repo.list_active_by_players_and_product(
                    player_ids_with_role, product_id
                )
            }

            for member in role_members:
                player = players_by_discord_id.get(member.id)
                has_license = player is not None and player.id in player_ids_with_active_license
                if not has_license:
                    await self._fix_divergence(
                        member, role, plan, grant=False, reason="Divergencia: cargo sem License ativa"
                    )
                    result.roles_removed += 1

            # direcao 2: License ACTIVE, mas falta o cargo (evento perdido,
            # bot offline no momento, membro reentrou e perdeu cargos).
            active_licenses = await license_repo.list_active_by_product(product_id)
            players_by_id = {
                p.id: p for p in await player_repo.list_by_ids([lic.player_id for lic in active_licenses])
            }

        for license_row in active_licenses:
            player = players_by_id.get(license_row.player_id)
            if player is None:
                continue
            member = guild.get_member(player.discord_id)
            if member is None:
                continue  # nao fetcha por membro faltante — muito caro pra um catalogo grande, cobre so cache local
            if role not in member.roles:
                await self._fix_divergence(
                    member, role, plan, grant=True, reason="Divergencia: License ativa sem cargo"
                )
                result.roles_granted += 1

    async def _fix_divergence(
        self, member: discord.Member, role: discord.Role, plan: Plan, *, grant: bool, reason: str
    ) -> None:
        try:
            if grant:
                await member.add_roles(role, reason=reason)
            else:
                await member.remove_roles(role, reason=reason)
        except discord.Forbidden:
            logger.warning("Sem permissao para corrigir cargo do plano %s na guild %s.", plan.id, plan.guild_id)
            return
        except discord.HTTPException:
            logger.exception("Falha ao corrigir cargo do plano %s na guild %s.", plan.id, plan.guild_id)
            return

        await self._bot.audit_log_service.record(
            guild_id=plan.guild_id,
            category=AuditLogCategory.SUBSCRIPTION,
            action=f"Reconciliacao: {reason}",
            target_id=member.id,
            details={"plan": plan.name, "product_id": str(plan.product_id), "role_id": role.id},
        )
