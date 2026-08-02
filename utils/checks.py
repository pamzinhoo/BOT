from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands

from database.models.guild_settings import GuildSettings
from database.models.permission_settings import PermissionSettings
from database.models.punishment import PunishmentType
from database.repositories.guild_settings_repository import GuildSettingsRepository
from database.repositories.permission_settings_repository import PermissionSettingsRepository

if TYPE_CHECKING:
    from core.bot import LimerenceBot

# acoes cujo fallback legado (sem override em permission_settings) e admin/staff/publico
_LEGACY_ADMIN_ACTIONS = {"auditoria", "config"}
_LEGACY_STAFF_ACTIONS = {
    "claim", "unclaim", "fechar", "reabrir", "excluir", "recurso_banimento", "analises",
}


class NotStaffError(app_commands.CheckFailure):
    """Usuario nao possui nenhum cargo de staff configurado."""


class NotAdminError(app_commands.CheckFailure):
    """Usuario nao possui permissao de administrador do bot."""


async def _get_guild_settings(interaction: discord.Interaction) -> GuildSettings | None:
    if interaction.guild_id is None:
        return None
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    async with bot.database.session() as session:
        return await GuildSettingsRepository(session).get_by_guild_id(interaction.guild_id)


def _member_role_ids(interaction: discord.Interaction) -> set[int]:
    if not isinstance(interaction.user, discord.Member):
        return set()
    return {role.id for role in interaction.user.roles}


def member_has_staff_role(member: discord.Member, settings: GuildSettings | None) -> bool:
    """Versao sem Interaction — usada fora de comandos/botoes (ex: listener de on_message)."""
    if member.guild_permissions.administrator:
        return True
    allowed = (
        {
            settings.moderator_role_id,
            settings.dev_role_id,
            settings.ceo_role_id,
            settings.owner_role_id,
            settings.support_role_id,
        }
        if settings
        else set()
    )
    role_ids = {role.id for role in member.roles}
    return bool(role_ids & {r for r in allowed if r is not None})


async def member_is_admin(interaction: discord.Interaction) -> bool:
    """True se o membro tem permissao de Administrador ou cargo Owner/Dev/CEO configurado."""
    if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator:
        return True
    settings = await _get_guild_settings(interaction)
    role_ids = _member_role_ids(interaction)
    allowed = (
        {settings.dev_role_id, settings.ceo_role_id, settings.owner_role_id} if settings else set()
    )
    return bool(role_ids & {r for r in allowed if r is not None})


async def member_is_staff(interaction: discord.Interaction) -> bool:
    """True se o membro tem permissao de Administrador ou cargo Moderador/Dev/CEO."""
    if not isinstance(interaction.user, discord.Member):
        return False
    settings = await _get_guild_settings(interaction)
    return member_has_staff_role(interaction.user, settings)


def is_admin() -> Any:
    async def predicate(interaction: discord.Interaction) -> bool:
        if await member_is_admin(interaction):
            return True
        raise NotAdminError()

    return app_commands.check(predicate)


async def member_is_owner_or_ceo(interaction: discord.Interaction) -> bool:
    """True se o membro tem permissao de Administrador ou cargo Owner/CEO configurado.
    Mais restrito que member_is_admin — nao inclui o cargo Dev. Usado pro reset geral
    de configuracoes (/config reset-all), que nunca deve ficar disponivel pra
    Moderador/Suporte/Dev."""
    if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator:
        return True
    settings = await _get_guild_settings(interaction)
    role_ids = _member_role_ids(interaction)
    allowed = {settings.ceo_role_id, settings.owner_role_id} if settings else set()
    return bool(role_ids & {r for r in allowed if r is not None})


def is_owner_or_ceo() -> Any:
    async def predicate(interaction: discord.Interaction) -> bool:
        if await member_is_owner_or_ceo(interaction):
            return True
        raise NotAdminError()

    return app_commands.check(predicate)


def is_staff() -> Any:
    async def predicate(interaction: discord.Interaction) -> bool:
        if await member_is_staff(interaction):
            return True
        raise NotStaffError()

    return app_commands.check(predicate)


async def _get_permission_settings(interaction: discord.Interaction) -> PermissionSettings | None:
    if interaction.guild_id is None:
        return None
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    async with bot.database.session() as session:
        return await PermissionSettingsRepository(session).get_by_guild_id(interaction.guild_id)


async def member_can(interaction: discord.Interaction, action: str) -> bool:
    """Checa se o membro pode executar `action` (claim/unclaim/fechar/reabrir/excluir/
    auditoria/ranking/config). Se a guild configurou cargos especificos pra essa acao em
    `permission_settings`, usa so isso. Senao, cai no comportamento padrao de sempre
    (staff pras acoes de ticket, admin pra auditoria/config, publico pro resto)."""
    if not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator:
        return True

    settings = await _get_permission_settings(interaction)
    role_ids: list[int] = getattr(settings, action, []) if settings is not None else []
    if role_ids:
        member_role_ids = {role.id for role in interaction.user.roles}
        return bool(member_role_ids & set(role_ids))

    if action in _LEGACY_ADMIN_ACTIONS:
        return await member_is_admin(interaction)
    if action in _LEGACY_STAFF_ACTIONS:
        return await member_is_staff(interaction)
    return True  # acoes sem fallback restrito (ex.: ranking) sao publicas por padrao


# Moderador so pode advertencia/timeout/kick — ban/ban_temporario exige Administrador/Owner.
_MODERATOR_ALLOWED_PUNISHMENT_TYPES = {
    PunishmentType.ADVERTENCIA,
    PunishmentType.TIMEOUT,
    PunishmentType.KICK,
}


async def member_can_apply_punishment(interaction: discord.Interaction, ptype: PunishmentType) -> bool:
    """Controle de permissoes de /punir (Etapa 9): Administrador/Owner podem qualquer tipo,
    Moderador so advertencia/timeout/kick, os demais nao podem punir."""
    if await member_is_admin(interaction):
        return True
    if await member_is_staff(interaction):
        return ptype in _MODERATOR_ALLOWED_PUNISHMENT_TYPES
    return False


def can_punish_target(staff: discord.Member, target: discord.Member) -> bool:
    """Protecao contra abuso de staff (Etapa 10): staff nao pode punir membro com cargo
    igual ou superior ao seu. Administrador do servidor sempre pode; ninguem pode punir
    o dono do servidor."""
    if target.id == target.guild.owner_id:
        return False
    if staff.guild_permissions.administrator:
        return True
    return staff.top_role > target.top_role


async def member_can_review_appeal(interaction: discord.Interaction, applied_by_staff_id: int) -> bool:
    """Staff responsavel pela punicao original nao pode analisar o proprio recurso (Etapa 20)."""
    if interaction.user.id == applied_by_staff_id:
        return False
    return await member_is_staff(interaction)


def member_can_create_invite(member: discord.Member, settings: PermissionSettings | None) -> bool:
    """Fora de interaction (listener de on_invite_create). Cargo(s) configurados em
    `convite` sao os unicos autorizados a criar convite; lista vazia = sem restricao
    (comportamento padrao do Discord)."""
    if member.guild_permissions.administrator:
        return True
    role_ids: list[int] = settings.convite if settings is not None else []
    if not role_ids:
        return True
    member_role_ids = {role.id for role in member.roles}
    return bool(member_role_ids & set(role_ids))


def has_permission(action: str) -> Any:
    async def predicate(interaction: discord.Interaction) -> bool:
        if await member_can(interaction, action):
            return True
        raise NotStaffError()

    return app_commands.check(predicate)
