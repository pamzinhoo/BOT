from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from core.event_bus import EventBus
from core.events import LICENSE_GRANT_EVENTS, LICENSE_REVOKE_EVENTS, LicenseEventPayload
from core.logger import get_logger
from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.plan import Plan
from database.repositories.guild_settings_repository import GuildSettingsRepository
from database.repositories.plan_repository import PlanRepository
from database.repositories.player_repository import PlayerRepository

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("role_sync_service")


class RoleSyncService:
    """Reage a eventos de License (via EventBus) concedendo cargo Discord.

    IMPORTANTE: este servico ficou propositalmente nao destrutivo tambem. O
    problema real visto em producao foi cargo manual/comunitario ("Dublador")
    sendo reutilizado por plano/DLC e removido em massa quando eventos de
    licenca revogada/expirada eram reprocessados no boot/sincronizacao. Por
    seguranca, evento de revoke/expire agora NAO remove cargo automaticamente.
    A remocao de cargos de planos deve ser uma acao explicita e auditavel,
    feita por uma tela/comando proprio, nao por rotina automatica.
    """

    def __init__(self, database: Database, bot: LimerenceBot) -> None:
        self._database = database
        self._bot = bot

    def register(self, event_bus: EventBus) -> None:
        for event_name in (*LICENSE_GRANT_EVENTS, *LICENSE_REVOKE_EVENTS):
            event_bus.subscribe(event_name, self.handle_license_event)

    async def handle_license_event(self, payload: LicenseEventPayload) -> None:
        grant = payload.event_type in LICENSE_GRANT_EVENTS
        if not grant:
            logger.warning(
                "RoleSync nao destrutivo bloqueou evento %s da license %s "
                "(product_id=%s, player_id=%s). Nenhum cargo sera removido "
                "automaticamente; remocao deve ser acao explicita.",
                payload.event_type,
                payload.license_id,
                payload.product_id,
                payload.player_id,
            )
            return

        async with self._database.session() as session:
            player = await PlayerRepository(session).get_by_id(payload.player_id)
            plans = await PlanRepository(session).list_by_product(payload.product_id)
        if player is None or not plans:
            return

        for plan in plans:
            try:
                await self._grant(plan, player.discord_id)
            except Exception:
                logger.exception(
                    "Falha ao sincronizar cargo do plano %s (guild %s) para discord_id %s.",
                    plan.id,
                    plan.guild_id,
                    player.discord_id,
                )

    async def handle_player_verified(self, discord_id: int) -> None:
        """Login com Discord concluido no launcher -> concede o cargo de
        verificado (GuildSettings.verified_role_id) em toda guild onde esse
        discord_id ja for membro e o cargo estiver configurado (/config ->
        Cargos).

        IMPORTANTE: este metodo so CONCEDE, nunca revoga.
        """
        async with self._database.session() as session:
            guild_settings_list = await GuildSettingsRepository(session).list_with_verified_role()

        for guild_settings in guild_settings_list:
            guild = self._bot.get_guild(guild_settings.guild_id)
            if guild is None or guild_settings.verified_role_id is None:
                continue
            role = guild.get_role(guild_settings.verified_role_id)
            if role is None:
                continue
            try:
                member = await self._get_member(guild, discord_id)
                if member is None or role in member.roles:
                    continue
                await member.add_roles(role, reason="Login com Discord no launcher")
                await self._bot.audit_log_service.record(
                    guild_id=guild.id,
                    category=AuditLogCategory.SUBSCRIPTION,
                    action="Cargo de verificado concedido (login no launcher)",
                    target_id=discord_id,
                    details={"role_id": role.id},
                )
            except Exception:
                logger.exception(
                    "Falha ao conceder cargo de verificado (guild %s) para discord_id %s.",
                    guild_settings.guild_id,
                    discord_id,
                )

    async def is_currently_verified(self, discord_id: int) -> bool:
        """Checagem AO VIVO (sem cache, sem banco intermediario) se
        `discord_id` tem, agora mesmo, o cargo de verificado em QUALQUER
        guild configurada.
        """
        async with self._database.session() as session:
            guild_settings_list = await GuildSettingsRepository(session).list_with_verified_role()

        for guild_settings in guild_settings_list:
            guild = self._bot.get_guild(guild_settings.guild_id)
            if guild is None or guild_settings.verified_role_id is None:
                continue
            role = guild.get_role(guild_settings.verified_role_id)
            if role is None:
                continue
            member = guild.get_member(discord_id)
            if member is not None and role in member.roles:
                return True
        return False

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
        """Bloqueio defensivo para chamadas antigas/diretas.

        Mesmo que algum ponto legado chame `_revoke` diretamente, este metodo
        nao remove cargos. Isso evita nova perda em massa de cargos manuais
        enquanto nao existir uma tela/comando explicito de revogacao segura.
        """
        logger.warning(
            "RoleSync nao destrutivo ignorou remocao direta do cargo do plano %s "
            "para discord_id %s na guild %s.",
            plan.id,
            discord_id,
            plan.guild_id,
        )

    async def _audit(self, plan: Plan, discord_id: int, *, action: str) -> None:
        await self._bot.audit_log_service.record(
            guild_id=plan.guild_id,
            category=AuditLogCategory.SUBSCRIPTION,
            action=action,
            target_id=discord_id,
            details={"plan": plan.name, "product_id": str(plan.product_id)},
        )
