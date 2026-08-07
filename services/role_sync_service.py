from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from core.event_bus import EventBus
from core.events import LICENSE_GRANT_EVENTS, LICENSE_REVOKE_EVENTS, LicenseEventPayload
from core.logger import get_logger
from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.plan import Plan
from database.repositories.plan_repository import PlanRepository
from database.repositories.player_repository import PlayerRepository

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("role_sync_service")


class RoleSyncService:
    """Reage a eventos de License (via EventBus) concedendo/removendo cargo
    Discord — a metade "bot" do fluxo da Fase 5: "Backend cria licenca ->
    Evento interno -> Bot concede cargo". Nunca decide posse por conta
    propria (isso e sempre LicenseService); so traduz o que o backend ja
    decidiu em uma acao no Discord, em TODOS os servidores onde algum Plano
    vincula esse Product a um cargo (PlanRepository.list_by_product)."""

    def __init__(self, database: Database, bot: LimerenceBot) -> None:
        self._database = database
        self._bot = bot

    def register(self, event_bus: EventBus) -> None:
        for event_name in (*LICENSE_GRANT_EVENTS, *LICENSE_REVOKE_EVENTS):
            event_bus.subscribe(event_name, self.handle_license_event)

    async def handle_license_event(self, payload: LicenseEventPayload) -> None:
        grant = payload.event_type in LICENSE_GRANT_EVENTS
        async with self._database.session() as session:
            player = await PlayerRepository(session).get_by_id(payload.player_id)
            plans = await PlanRepository(session).list_by_product(payload.product_id)
        if player is None or not plans:
            return

        for plan in plans:
            try:
                if grant:
                    await self._grant(plan, player.discord_id)
                else:
                    await self._revoke(plan, player.discord_id)
            except Exception:
                logger.exception(
                    "Falha ao sincronizar cargo do plano %s (guild %s) para discord_id %s.",
                    plan.id,
                    plan.guild_id,
                    player.discord_id,
                )

    # --- Discord ----------------------------------------------------------

    async def _get_member(self, guild: discord.Guild, discord_id: int) -> discord.Member | None:
        member = guild.get_member(discord_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(discord_id)
        except discord.HTTPException:
            return None

    async def _grant(self, plan: Plan, discord_id: int) -> None:
        guild = self._bot.get_guild(plan.guild_id)
        if guild is None or plan.role_id is None:
            return
        role = guild.get_role(plan.role_id)
        if role is None:
            return
        member = await self._get_member(guild, discord_id)
        if member is None or role in member.roles:
            return
        await member.add_roles(role, reason="Sincronizacao de licenca (backend)")
        await self._audit(plan, discord_id, action="Cargo concedido (evento de licenca)")

    async def _revoke(self, plan: Plan, discord_id: int) -> None:
        guild = self._bot.get_guild(plan.guild_id)
        if guild is None or plan.role_id is None:
            return
        role = guild.get_role(plan.role_id)
        if role is None:
            return
        member = await self._get_member(guild, discord_id)
        if member is None or role not in member.roles:
            return
        await member.remove_roles(role, reason="Sincronizacao de licenca (backend)")
        await self._audit(plan, discord_id, action="Cargo removido (evento de licenca)")

    async def _audit(self, plan: Plan, discord_id: int, *, action: str) -> None:
        await self._bot.audit_log_service.record(
            guild_id=plan.guild_id,
            category=AuditLogCategory.SUBSCRIPTION,
            action=action,
            target_id=discord_id,
            details={"plan": plan.name, "product_id": str(plan.product_id)},
        )
