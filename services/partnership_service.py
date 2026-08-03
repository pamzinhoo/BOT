from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import discord
from sqlalchemy.exc import IntegrityError

from core.logger import get_logger
from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.partnership import Partnership
from database.models.partnership_settings import PartnershipMode, PartnershipSettings
from database.repositories.partnership_repository import PartnershipRepository
from database.repositories.partnership_settings_repository import PartnershipSettingsRepository
from utils.time import humanize_duration

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("partnership_service")

DEFAULT_PRE_MESSAGE = (
    "📢 {here}\n\nNosso parceiro acabou de atualizar sua divulgação!\n\nConfira as novidades abaixo."
)

_EXTERNAL_LINK_PATTERN = re.compile(r"https?://", re.IGNORECASE)
_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9]+")


class PartnershipError(ValueError):
    """Erro de negocio no fluxo de parcerias (mostrado direto pro usuario)."""


@dataclass
class PartnershipCooldownError(PartnershipError):
    retry_after: timedelta

    def __str__(self) -> str:
        return f"Aguarde {humanize_duration(int(self.retry_after.total_seconds()))} antes de publicar novamente."


def slugify(name: str, *, fallback: str = "parceiro") -> str:
    slug = _SLUG_INVALID_CHARS.sub("-", name.strip().lower()).strip("-")
    return (slug or fallback)[:90]


def contains_external_link(text: str) -> bool:
    return _EXTERNAL_LINK_PATTERN.search(text) is not None


def cooldown_remaining(
    cooldown_hours: int, last_publish_at: datetime | None, now: datetime
) -> timedelta | None:
    """Pura e testavel: quanto falta pro parceiro poder publicar de novo, ou
    None se ja pode (primeira publicacao ou cooldown ja passou)."""
    if last_publish_at is None:
        return None
    if last_publish_at.tzinfo is None:
        last_publish_at = last_publish_at.replace(tzinfo=UTC)
    elapsed = now - last_publish_at
    remaining = timedelta(hours=cooldown_hours) - elapsed
    return remaining if remaining > timedelta(0) else None


def render_pre_message(template: str, *, allow_here: bool) -> str:
    here = "@here" if allow_here else ""
    rendered = template.replace("{here}", here)
    return "\n".join(line for line in rendered.splitlines() if line.strip()) or rendered


def member_has_role(member: discord.Member, role_id: int | None) -> bool:
    if role_id is None:
        return False
    return any(role.id == role_id for role in member.roles)


def member_is_partnership_staff(member: discord.Member, settings: PartnershipSettings) -> bool:
    if member.guild_permissions.administrator:
        return True
    return member_has_role(member, settings.staff_role_id)


@dataclass
class _Space:
    """Onde a publicacao do parceiro vai (canal existente, topico existente, ou
    canal de forum ainda sem topico — 1a publicacao em modo Forum)."""

    kind: Literal["channel", "thread", "forum_new"]
    target: discord.abc.Messageable
    new_channel_id: int | None = None
    new_role_id: int | None = None


class PartnershipService:
    """Sistema de parcerias/streamers: cada parceiro tem um canal (ou topico de
    forum) permanente e proprio, criado automaticamente na primeira
    publicacao e reaproveitado nas seguintes — nunca duplicado."""

    def __init__(self, database: Database, bot: LimerenceBot) -> None:
        self._database = database
        self._bot = bot

    # --- configuracao -----------------------------------------------------

    async def get_settings(self, guild_id: int) -> PartnershipSettings:
        async with self._database.session() as session:
            return await PartnershipSettingsRepository(session).get_or_create(guild_id)

    async def update_settings(self, guild_id: int, **fields: object) -> PartnershipSettings:
        async with self._database.session() as session:
            repo = PartnershipSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
            await session.flush()
            await session.refresh(settings)
        return settings

    # --- consulta -----------------------------------------------------------

    async def get_partnership(self, guild_id: int, owner_id: int) -> Partnership | None:
        async with self._database.session() as session:
            return await PartnershipRepository(session).get_by_guild_owner(guild_id, owner_id)

    # --- publicacao ----------------------------------------------------------

    async def publish(
        self,
        *,
        guild: discord.Guild,
        member: discord.Member,
        name: str,
        description: str,
        invite: str | None,
        banner: str | None,
        category_label: str | None,
    ) -> Partnership:
        settings = await self.get_settings(guild.id)
        partner_role_id = await self._get_guild_partner_role_id(guild.id)

        if not settings.enabled:
            raise PartnershipError("O sistema de parcerias está desativado neste servidor.")
        if not member_has_role(member, partner_role_id):
            raise PartnershipError("Você não possui o cargo necessário para publicar uma parceria.")

        name = name.strip()[:100]
        description = description.strip()
        if len(description) > settings.max_description_length:
            raise PartnershipError(
                f"A descrição excede o limite de {settings.max_description_length} caracteres."
            )
        if not settings.allow_external_links and contains_external_link(description):
            raise PartnershipError("Links externos não são permitidos na descrição.")

        banner = banner.strip() if banner and banner.strip() else None
        if banner is not None and not settings.allow_banner:
            banner = None
        invite = invite.strip() if invite and invite.strip() else None
        if invite is not None and not settings.allow_invite:
            invite = None
        category_label = category_label.strip()[:100] if category_label and category_label.strip() else None

        now = datetime.now(UTC)
        record, is_new = await self._upsert_record(
            guild.id, member.id, name=name, description=description, invite=invite, banner=banner,
            category_label=category_label, settings=settings, now=now,
        )

        space = await self._ensure_space(guild, member, settings, record, partner_role_id)
        if space.new_channel_id is not None or space.new_role_id is not None:
            ids: dict[str, object] = {}
            if space.new_channel_id is not None:
                ids["channel_id"] = space.new_channel_id
            if space.new_role_id is not None:
                ids["role_id"] = space.new_role_id
            record = await self._persist_ids(record.id, **ids)

        if record.message_id is not None:
            await self._delete_old_message(space, record.message_id)

        message, new_thread_id = await self._send_publication(space, settings, record)

        publication_ids: dict[str, object] = {"message_id": message.id, "last_publish_at": now}
        if new_thread_id is not None:
            publication_ids["thread_id"] = new_thread_id
        record = await self._persist_ids(record.id, **publication_ids)

        await self._record_audit(
            guild_id=guild.id,
            action="Parceria criada" if is_new else "Parceria atualizada",
            executor_id=member.id,
            executor_name=str(member),
            target_id=member.id,
            target_name=str(member),
            details={"nome": record.name},
        )
        await self._send_log(guild, settings, record, action="Publicação atualizada")
        return record

    async def _upsert_record(
        self,
        guild_id: int,
        owner_id: int,
        *,
        name: str,
        description: str,
        invite: str | None,
        banner: str | None,
        category_label: str | None,
        settings: PartnershipSettings,
        now: datetime,
    ) -> tuple[Partnership, bool]:
        async with self._database.session() as session:
            repo = PartnershipRepository(session)
            record = await repo.get_by_guild_owner_locked(guild_id, owner_id)

            if record is not None:
                remaining = cooldown_remaining(settings.cooldown_hours, record.last_publish_at, now)
                if remaining is not None:
                    raise PartnershipCooldownError(remaining)
                record.name = name
                record.description = description
                record.invite = invite
                record.banner = banner
                record.category_label = category_label
                await session.flush()
                await session.refresh(record)
                return record, False

            try:
                record = await repo.add(
                    Partnership(
                        guild_id=guild_id, owner_id=owner_id, name=name, description=description,
                        invite=invite, banner=banner, category_label=category_label,
                    )
                )
                await session.flush()
                await session.refresh(record)
            except IntegrityError as exc:
                raise PartnershipError(
                    "Já existe uma parceria em andamento para você. Tente novamente."
                ) from exc
            return record, True

    async def _persist_ids(self, partnership_id: uuid.UUID, **ids: object) -> Partnership:
        async with self._database.session() as session:
            repo = PartnershipRepository(session)
            record = await repo.get_by_id(partnership_id)
            assert record is not None
            for key, value in ids.items():
                setattr(record, key, value)
            await session.flush()
            await session.refresh(record)
        return record

    # --- espaco (canal/topico) do parceiro ------------------------------------

    async def _get_guild_partner_role_id(self, guild_id: int) -> int | None:
        guild_settings = await self._bot.config_service.get_settings(guild_id)
        return guild_settings.partner_role_id

    async def _ensure_space(
        self,
        guild: discord.Guild,
        member: discord.Member,
        settings: PartnershipSettings,
        record: Partnership,
        partner_role_id: int | None,
    ) -> _Space:
        existing = self._resolve_existing_space(guild, record)
        if existing is not None:
            return existing
        return await self._create_space(guild, member, settings, record, partner_role_id)

    def _resolve_existing_space(self, guild: discord.Guild, record: Partnership) -> _Space | None:
        if record.channel_id is not None:
            channel = guild.get_channel(record.channel_id)
            if isinstance(channel, discord.abc.Messageable):
                return _Space(kind="channel", target=channel)
            return None
        if record.thread_id is not None:
            thread = guild.get_thread(record.thread_id)
            if thread is not None:
                return _Space(kind="thread", target=thread)
            return None
        return None

    async def _create_space(
        self,
        guild: discord.Guild,
        member: discord.Member,
        settings: PartnershipSettings,
        record: Partnership,
        partner_role_id: int | None,
    ) -> _Space:
        mode = PartnershipMode(settings.mode)

        if mode == PartnershipMode.FORUM:
            forum = guild.get_channel(settings.forum_channel_id) if settings.forum_channel_id else None
            if not isinstance(forum, discord.ForumChannel):
                raise PartnershipError(
                    "O fórum de parcerias configurado não existe mais neste servidor. Avise a staff."
                )
            # Threads de forum nao suportam overwrite de permissao proprio (API
            # do Discord) — o controle de quem posta fica a cargo das
            # permissoes gerais do canal de forum configurado pela staff.
            return _Space(kind="forum_new", target=forum)

        category = None
        if settings.category_channel_id is not None:
            candidate = guild.get_channel(settings.category_channel_id)
            category = candidate if isinstance(candidate, discord.CategoryChannel) else None
            if category is None:
                raise PartnershipError(
                    "A categoria de parcerias configurada não existe mais neste servidor. Avise a staff."
                )

        role: discord.Role | None = None
        try:
            role = await guild.create_role(
                name=record.name[:100], reason=f"Parceria: cargo dedicado de {member}"
            )
            await member.add_roles(role, reason="Parceria: cargo do parceiro")
        except discord.HTTPException:
            logger.warning("Falha ao criar/atribuir cargo dedicado de parceria na guild %s.", guild.id)
            role = None

        overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True, send_messages=False, read_message_history=True
            ),
        }
        for role_id in (settings.staff_role_id, partner_role_id):
            configured_role = guild.get_role(role_id) if role_id else None
            if configured_role is not None:
                overwrites[configured_role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

        channel = await guild.create_text_channel(
            name=slugify(record.name), category=category, overwrites=overwrites,
            reason=f"Parceria criada por {member}",
        )
        return _Space(kind="channel", target=channel, new_channel_id=channel.id, new_role_id=role.id if role else None)

    # --- publicacao (mensagem) -----------------------------------------------

    async def _delete_old_message(self, space: _Space, message_id: int) -> None:
        if space.kind == "forum_new":
            return  # topico de forum ainda nem existe — nao ha mensagem antiga
        try:
            message = await space.target.fetch_message(message_id)
        except discord.NotFound:
            return  # ja tinha sido apagada manualmente — ignora, segue o fluxo
        except discord.HTTPException:
            logger.warning("Falha ao buscar mensagem antiga de parceria (id=%s).", message_id)
            return
        try:
            await message.delete()
        except discord.NotFound:
            pass  # ja tinha sido apagada manualmente — ignora, segue o fluxo
        except discord.HTTPException:
            logger.warning("Falha ao apagar mensagem antiga de parceria (id=%s).", message_id)

    async def _send_publication(
        self, space: _Space, settings: PartnershipSettings, record: Partnership
    ) -> tuple[discord.Message, int | None]:
        """Publica a mensagem no espaco do parceiro. Devolve (mensagem,
        thread_id) — thread_id so vem preenchido quando um topico de forum
        precisou ser criado agora (1a publicacao em modo Forum)."""
        from views.embeds import partnership_embed

        embed = partnership_embed(record, allow_image=settings.allow_image)
        template = settings.pre_message or DEFAULT_PRE_MESSAGE
        content = render_pre_message(template, allow_here=settings.allow_here)

        if space.kind == "forum_new":
            forum = space.target
            assert isinstance(forum, discord.ForumChannel)
            result = await forum.create_thread(
                name=slugify(record.name), content=content or None, embed=embed
            )
            return result.message, result.thread.id

        message = await space.target.send(content=content or None, embed=embed)
        return message, None

    # --- remocao --------------------------------------------------------------

    async def remove(
        self,
        *,
        guild: discord.Guild,
        actor: discord.Member,
        owner: discord.Member | None = None,
        channel_id: int | None = None,
    ) -> Partnership:
        settings = await self.get_settings(guild.id)
        if not member_is_partnership_staff(actor, settings):
            raise PartnershipError("Apenas a staff pode remover parcerias.")

        async with self._database.session() as session:
            repo = PartnershipRepository(session)
            record = None
            if owner is not None:
                record = await repo.get_by_guild_owner(guild.id, owner.id)
            elif channel_id is not None:
                record = await repo.get_by_channel_or_thread(guild.id, channel_id)
            if record is None:
                raise PartnershipError("Nenhuma parceria encontrada para remover.")

            channel_id_to_delete = record.channel_id
            thread_id_to_delete = record.thread_id
            role_id_to_delete = record.role_id
            owner_id = record.owner_id
            name = record.name
            await repo.delete(record)

        if channel_id_to_delete is not None:
            channel = guild.get_channel(channel_id_to_delete)
            if channel is not None:
                try:
                    await channel.delete(reason=f"Parceria removida por {actor}")
                except discord.HTTPException:
                    logger.warning("Falha ao apagar canal de parceria %s.", channel_id_to_delete)
        if thread_id_to_delete is not None:
            thread = guild.get_thread(thread_id_to_delete)
            if thread is not None:
                try:
                    await thread.delete()
                except discord.HTTPException:
                    logger.warning("Falha ao apagar tópico de parceria %s.", thread_id_to_delete)
        if role_id_to_delete is not None:
            role = guild.get_role(role_id_to_delete)
            if role is not None:
                try:
                    await role.delete(reason=f"Parceria removida por {actor}")
                except discord.HTTPException:
                    logger.warning("Falha ao apagar cargo de parceria %s.", role_id_to_delete)

        await self._record_audit(
            guild_id=guild.id,
            action="Parceria removida",
            executor_id=actor.id,
            executor_name=str(actor),
            target_id=owner_id,
            details={"nome": name},
        )
        return record

    # --- auditoria / logs -----------------------------------------------------

    async def _send_log(
        self, guild: discord.Guild, settings: PartnershipSettings, record: Partnership, *, action: str
    ) -> None:
        if settings.log_channel_id is None:
            return
        channel = guild.get_channel(settings.log_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return
        from views.embeds import partnership_log_embed

        try:
            await channel.send(embed=partnership_log_embed(record, action=action))
        except discord.HTTPException:
            logger.exception("Falha ao enviar log de parceria na guild %s.", guild.id)

    async def _record_audit(
        self,
        *,
        guild_id: int,
        action: str,
        executor_id: int | None = None,
        executor_name: str | None = None,
        target_id: int | None = None,
        target_name: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        await self._bot.audit_log_service.record(
            guild_id=guild_id,
            category=AuditLogCategory.PARTNERSHIP,
            action=action,
            executor_id=executor_id,
            executor_name=executor_name,
            target_id=target_id,
            target_name=target_name,
            details=details or {},
        )
