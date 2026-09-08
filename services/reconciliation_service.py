from __future__ import annotations

import asyncio
import time
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

# Retry curto e limitado so pra erro transiente da API Discord (5xx/rede) na
# escrita do cargo — Forbidden/NotFound sao permanentes, nao adianta tentar
# de novo (ver _fix_divergence). discord.py ja lida com 429 internamente
# (fila de rate limit do proprio HTTP client), entao isto NAO e retry de
# rate limit, e so de falha transiente pontual.
_ROLE_EDIT_MAX_ATTEMPTS = 2
_ROLE_EDIT_RETRY_BACKOFF_SECONDS = 1.0


@dataclass
class GuildReconciliationResult:
    guild_id: int
    roles_granted: int = 0
    roles_removed: int = 0
    errors: int = 0
    timed_out: bool = False


@dataclass
class ReconciliationReport:
    guilds_checked: int = 0
    roles_granted: int = 0
    roles_removed: int = 0
    errors: int = 0
    timeouts: int = 0
    duration_seconds: float = 0.0
    max_concurrency: int = 0
    per_guild: list[GuildReconciliationResult] = field(default_factory=list)


class ReconciliationService:
    """Reconciliacao periodica entre License (backend, fonte de verdade) e
    cargo Discord (bot, reflexo).

    Esta rotina e' propositalmente nao destrutiva: ela pode CONCEDER cargos
    faltantes quando existe License ACTIVE, mas nao remove cargos que alguem
    tem no Discord sem License ativa. Remocao automatica de cargo fica restrita
    a eventos explicitos de revogacao/cancelamento tratados pelo
    RoleSyncService. Isso evita que cargos dados manualmente, reutilizados em
    staff/comunidade ou configurados por engano em um plano/DLC sejam removidos
    em massa quando o bot/painel inicia.
    """

    def __init__(
        self,
        database: Database,
        bot: LimerenceBot,
        *,
        max_concurrency: int = 5,
        guild_timeout_seconds: float = 30,
    ) -> None:
        self._database = database
        self._bot = bot
        self._max_concurrency = max_concurrency
        self._guild_timeout_seconds = guild_timeout_seconds
        # O ciclo periodico (LicenseReconciliationCog) e o endpoint sob
        # demanda (/internal/reconcile) chamam o mesmo metodo — sem trava,
        # dois disparos quase simultaneos rodariam duas reconciliacoes
        # completas em paralelo (duplicando idas ao banco/Discord e linhas
        # de auditoria). A trava so serializa: o segundo disparo espera o
        # primeiro terminar em vez de correr junto.
        self._lock = asyncio.Lock()

    async def reconcile_all_guilds(self) -> ReconciliationReport:
        async with self._lock:
            start = time.monotonic()
            report = ReconciliationReport(max_concurrency=self._max_concurrency)
            guilds = list(self._bot.guilds)
            # Semaforo limita quantas guilds reconciliam ao mesmo tempo —
            # sem isso, `gather` dispara todas de uma vez (N sessoes de DB +
            # N rajadas de chamadas Discord concorrentes), competindo com o
            # event loop que tambem serve comandos/eventos do bot em tempo
            # real. `return_exceptions=True` continua garantindo que uma
            # guild travada/com erro nao cancela as demais.
            semaphore = asyncio.Semaphore(self._max_concurrency)
            results = await asyncio.gather(
                *(self._reconcile_guild_limited(guild, semaphore) for guild in guilds),
                return_exceptions=True,
            )
            for guild, result in zip(guilds, results, strict=True):
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
                if result.timed_out:
                    report.timeouts += 1
                report.per_guild.append(result)

            report.duration_seconds = time.monotonic() - start
            logger.info(
                "Reconciliation completed: guilds=%s success=%s failed=%s timeout=%s "
                "duration=%.1fs max_concurrency=%s",
                len(guilds),
                report.guilds_checked - report.timeouts,
                report.errors,
                report.timeouts,
                report.duration_seconds,
                report.max_concurrency,
            )
            return report

    async def _reconcile_guild_limited(
        self, guild: discord.Guild, semaphore: asyncio.Semaphore
    ) -> GuildReconciliationResult:
        async with semaphore:
            guild_start = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    self.reconcile_guild(guild), timeout=self._guild_timeout_seconds
                )
            except TimeoutError:
                logger.warning(
                    "Timeout ao reconciliar guild %s apos %.1fs (limite=%ss).",
                    guild.id,
                    time.monotonic() - guild_start,
                    self._guild_timeout_seconds,
                )
                return GuildReconciliationResult(guild_id=guild.id, errors=1, timed_out=True)
            logger.debug(
                "Guild %s reconciliada em %.2fs.", guild.id, time.monotonic() - guild_start
            )
            return result

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

        async with self._database.session() as session:
            license_repo = LicenseRepository(session)
            player_repo = PlayerRepository(session)

            # Direcao segura: License ACTIVE, mas falta o cargo (evento perdido,
            # bot offline no momento, membro reentrou e perdeu cargos).
            # A direcao oposta NAO remove cargo aqui. Cargos podem ter sido dados
            # manualmente ou reutilizados em staff/comunidade; remover em varredura
            # de startup causou perda em massa de cargos como Dublador.
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
        if not grant:
            logger.warning(
                "Reconciliacao nao destrutiva bloqueou remocao do cargo %s (%s) "
                "do membro %s na guild %s. Remocoes automaticas devem vir de "
                "evento explicito de revogacao/cancelamento.",
                role.name,
                role.id,
                member.id,
                plan.guild_id,
            )
            return

        for attempt in range(1, _ROLE_EDIT_MAX_ATTEMPTS + 1):
            try:
                await member.add_roles(role, reason=reason)
                break
            except (discord.Forbidden, discord.NotFound) as exc:
                # Permanente (sem permissao / cargo ou membro sumiu) — retry
                # nao resolve, so tenta de novo no proximo ciclo.
                logger.warning(
                    "Falha permanente ao corrigir cargo do plano %s na guild %s: %s.",
                    plan.id,
                    plan.guild_id,
                    type(exc).__name__,
                )
                return
            except discord.HTTPException:
                if attempt >= _ROLE_EDIT_MAX_ATTEMPTS:
                    logger.exception(
                        "Falha ao corrigir cargo do plano %s na guild %s apos %s tentativa(s).",
                        plan.id,
                        plan.guild_id,
                        attempt,
                    )
                    return
                await asyncio.sleep(_ROLE_EDIT_RETRY_BACKOFF_SECONDS * attempt)

        await self._bot.audit_log_service.record(
            guild_id=plan.guild_id,
            category=AuditLogCategory.SUBSCRIPTION,
            action=f"Reconciliacao: {reason}",
            target_id=member.id,
            details={"plan": plan.name, "product_id": str(plan.product_id), "role_id": role.id},
        )
