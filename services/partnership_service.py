from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord
from sqlalchemy.exc import IntegrityError

from core.logger import get_logger
from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.partnership import Partnership
from database.models.partnership_settings import PartnershipRoleRemovedAction, PartnershipSettings
from database.repositories.partnership_repository import PartnershipRepository
from database.repositories.partnership_settings_repository import PartnershipSettingsRepository

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("partnership_service")

ARCHIVE_CATEGORY_NAME = "Parceiros Antigos"

DEFAULT_WELCOME_MESSAGE = (
    "👋 Bem-vindo ao seu canal de parceiro!\n\n"
    "Aqui você pode divulgar sua comunidade, loja, canal, empresa, projeto ou "
    "conteúdo da forma que preferir.\n\n"
    "Você pode:\n\n"
    "• alterar o nome do canal;\n"
    "• personalizar a descrição;\n"
    "• enviar imagens;\n"
    "• enviar vídeos;\n"
    "• publicar novidades sempre que desejar.\n\n"
    "Este espaço é totalmente seu dentro das regras do servidor.\n\n"
    "O bot fará divulgações automáticas deste canal conforme as configurações "
    "definidas pela administração.\n\n"
    "Desejamos muito sucesso!"
)

DEFAULT_ANNOUNCEMENT_MESSAGE = "📢 Confira um de nossos parceiros!\n\n➡️ {channel}"

_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9]+")


class PartnershipError(ValueError):
    """Erro de negocio no fluxo de parcerias (mostrado direto pro usuario)."""


def slugify(name: str, *, fallback: str = "parceiro") -> str:
    slug = _SLUG_INVALID_CHARS.sub("-", name.strip().lower()).strip("-")
    return (slug or fallback)[:90]


def member_has_role(member: discord.Member, role_id: int | None) -> bool:
    if role_id is None:
        return False
    return any(role.id == role_id for role in member.roles)


def member_has_partnership_role(
    member: discord.Member, partner_role_id: int | None, streamer_role_id: int | None
) -> bool:
    return member_has_role(member, partner_role_id) or member_has_role(member, streamer_role_id)


def member_is_partnership_staff(member: discord.Member, settings: PartnershipSettings) -> bool:
    if member.guild_permissions.administrator:
        return True
    return member_has_role(member, settings.staff_role_id)


def render_announcement(template: str, *, channel_id: int, mention_type: str) -> str:
    mention = {"here": "@here", "everyone": "@everyone"}.get(mention_type, "")
    rendered = template.replace("{channel}", f"<#{channel_id}>").replace("{mention}", mention)
    return "\n".join(line for line in rendered.splitlines() if line.strip()) or rendered


class PartnershipService:
    """Sistema de parcerias/streamers: ao receber o cargo configurado, o bot cria
    (ou reaproveita) um canal proprio do parceiro automaticamente — toda a
    divulgacao em si e feita manualmente por ele dentro do canal. O bot so cuida
    de canal/permissoes/arquivamento e dispara avisos periodicos apontando pro
    canal (rodizio entre os parceiros ativos)."""

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

    async def get_partner_role_ids(self, guild_id: int) -> tuple[int | None, int | None]:
        """Cargos Parceiro/Streamer vivem em GuildSettings (/config -> Cargos),
        nao em PartnershipSettings."""
        guild_settings = await self._bot.config_service.get_settings(guild_id)
        return guild_settings.partner_role_id, guild_settings.streamer_role_id

    # --- consulta -----------------------------------------------------------

    async def get_partnership(self, guild_id: int, owner_id: int) -> Partnership | None:
        async with self._database.session() as session:
            return await PartnershipRepository(session).get_by_guild_owner(guild_id, owner_id)

    # --- fluxo: cargo recebido -------------------------------------------------

    async def handle_role_gained(self, member: discord.Member) -> None:
        guild = member.guild
        settings = await self.get_settings(guild.id)
        if not settings.enabled or not settings.auto_create:
            return

        partner_role_id, streamer_role_id = await self.get_partner_role_ids(guild.id)
        record = await self.get_partnership(guild.id, member.id)

        if record is None:
            await self._create_new(guild, member, settings, partner_role_id, streamer_role_id)
            return

        channel = guild.get_channel(record.channel_id) if record.channel_id else None
        if channel is None:
            # canal foi excluido manualmente — o registro antigo vira lixo:
            # apaga antes de criar de novo (evita violar a unique constraint).
            await self._delete_record(record.id)
            await self._create_new(guild, member, settings, partner_role_id, streamer_role_id)
            return

        if record.archived_at is not None:
            await self._restore(guild, settings, record, channel, partner_role_id, streamer_role_id)
            return

        # ja ativo — so garante que as permissoes estao corretas (idempotente)
        dedicated_role = guild.get_role(record.role_id) if record.role_id else None
        await self._apply_overwrites(
            channel, guild, settings, partner_role_id, streamer_role_id, dedicated_role, readonly=False
        )

    # --- fluxo: cargo removido ---------------------------------------------

    async def handle_role_lost(self, member: discord.Member) -> None:
        guild = member.guild
        settings = await self.get_settings(guild.id)
        record = await self.get_partnership(guild.id, member.id)
        if record is None or record.archived_at is not None:
            return  # nada ativo pra reagir

        action = settings.role_removed_action
        if action == PartnershipRoleRemovedAction.NONE.value:
            return

        channel = guild.get_channel(record.channel_id) if record.channel_id else None
        if channel is None:
            return  # canal ja nao existe mais — nada a fazer

        if action == PartnershipRoleRemovedAction.DELETE.value:
            await self._delete_channel_and_role(guild, record, channel)
        else:
            await self._archive(guild, settings, record, channel)

    # --- reconciliacao periodica ---------------------------------------------

    async def reconcile_guild(self, guild: discord.Guild) -> None:
        """on_member_update e a fonte oficial de deteccao, mas se o bot ficar
        offline exatamente durante o ganho/perda do cargo (deploy, crash, gap de
        resume do gateway) esse evento nunca chega. Chamado periodicamente pra
        comparar quem tem o cargo Parceiro/Streamer agora contra os registros
        ativos no banco, corrigindo qualquer divergencia via os mesmos handlers
        idempotentes do evento normal."""
        settings = await self.get_settings(guild.id)
        if not settings.enabled:
            return

        partner_role_id, streamer_role_id = await self.get_partner_role_ids(guild.id)
        holder_ids: set[int] = set()
        for role_id in {partner_role_id, streamer_role_id}:
            role = guild.get_role(role_id) if role_id else None
            if role is not None:
                holder_ids.update(m.id for m in role.members)

        async with self._database.session() as session:
            active = await PartnershipRepository(session).list_active_by_guild(guild.id)
        active_owner_ids = {record.owner_id for record in active}

        for owner_id in holder_ids - active_owner_ids:
            member = guild.get_member(owner_id)
            if member is not None:
                await self.handle_role_gained(member)

        for owner_id in active_owner_ids - holder_ids:
            member = guild.get_member(owner_id)
            if member is not None:
                await self.handle_role_lost(member)

    # --- divulgacao automatica (rodizio) --------------------------------------

    async def run_announcement_tick(self, guild: discord.Guild) -> None:
        settings = await self.get_settings(guild.id)
        if not settings.enabled or settings.announcement_channel_id is None:
            return

        now = datetime.now(UTC)
        if settings.last_announcement_at is not None:
            elapsed_minutes = (now - settings.last_announcement_at).total_seconds() / 60
            if elapsed_minutes < settings.announcement_interval_minutes:
                return

        channel = guild.get_channel(settings.announcement_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return

        async with self._database.session() as session:
            repo = PartnershipRepository(session)
            partner = await repo.get_next_to_announce(guild.id)
            if partner is None:
                partner_channel_id = None
                owner_id = None
            else:
                partner.last_announced_at = now
                partner_channel_id = partner.channel_id
                owner_id = partner.owner_id
                await session.flush()

        await self.update_settings(guild.id, last_announcement_at=now)
        if partner_channel_id is None:
            return

        template = settings.announcement_message or DEFAULT_ANNOUNCEMENT_MESSAGE
        content = render_announcement(template, channel_id=partner_channel_id, mention_type=settings.mention_type)
        mentions = discord.AllowedMentions(
            everyone=settings.mention_type in ("here", "everyone"),
        )
        try:
            await channel.send(content, allowed_mentions=mentions)
        except discord.HTTPException:
            logger.exception("Falha ao enviar divulgação automática na guild %s.", guild.id)
            return

        await self._record_audit(
            guild_id=guild.id,
            action="Divulgação enviada",
            target_id=owner_id,
            details={"channel_id": partner_channel_id},
        )

    # --- criacao / restauracao / arquivamento / exclusao do canal -------------

    async def _create_new(
        self,
        guild: discord.Guild,
        member: discord.Member,
        settings: PartnershipSettings,
        partner_role_id: int | None,
        streamer_role_id: int | None,
    ) -> None:
        category = self._resolve_category(guild, settings.category_channel_id)

        role: discord.Role | None = None
        try:
            role = await guild.create_role(
                name=member.display_name[:100], reason=f"Parceria: cargo dedicado de {member}"
            )
            await member.add_roles(role, reason="Parceria: cargo do parceiro")
        except discord.HTTPException:
            logger.warning("Falha ao criar/atribuir cargo dedicado de parceria na guild %s.", guild.id)
            role = None

        overwrites = self._build_overwrites(guild, settings, partner_role_id, streamer_role_id, role, readonly=False)
        channel_name = f"📢・{slugify(member.display_name)}"
        try:
            channel = await guild.create_text_channel(
                name=channel_name, category=category, overwrites=overwrites,
                reason=f"Parceria criada para {member}",
            )
        except discord.HTTPException:
            logger.exception("Falha ao criar canal de parceria pra %s na guild %s.", member.id, guild.id)
            return

        async with self._database.session() as session:
            repo = PartnershipRepository(session)
            try:
                await repo.add(
                    Partnership(
                        guild_id=guild.id, owner_id=member.id, channel_id=channel.id,
                        role_id=role.id if role else None,
                    )
                )
                await session.flush()
            except IntegrityError:
                logger.warning(
                    "Parceria de %s na guild %s ja existia (corrida entre eventos) — descartando canal extra.",
                    member.id, guild.id,
                )
                await channel.delete(reason="Parceria: canal duplicado descartado")
                return

        await self._send_welcome_message(channel, settings)
        await self._record_audit(
            guild_id=guild.id, action="Canal criado", executor_id=member.id, executor_name=str(member),
            target_id=member.id, target_name=str(member), details={"channel_id": channel.id},
        )

    async def _restore(
        self,
        guild: discord.Guild,
        settings: PartnershipSettings,
        record: Partnership,
        channel: discord.abc.GuildChannel,
        partner_role_id: int | None,
        streamer_role_id: int | None,
    ) -> None:
        category = self._resolve_category(guild, settings.category_channel_id)
        dedicated_role = guild.get_role(record.role_id) if record.role_id else None

        if category is not None and channel.category_id != category.id:
            try:
                await channel.edit(category=category, reason="Parceria: canal restaurado")
            except discord.HTTPException:
                logger.exception("Falha ao mover canal de parceria %s de volta pra categoria ativa.", channel.id)

        await self._apply_overwrites(
            channel, guild, settings, partner_role_id, streamer_role_id, dedicated_role, readonly=False
        )

        async with self._database.session() as session:
            repo = PartnershipRepository(session)
            db_record = await repo.get_by_id(record.id)
            assert db_record is not None
            db_record.archived_at = None
            await session.flush()

        await self._record_audit(
            guild_id=guild.id, action="Canal restaurado", target_id=record.owner_id,
            details={"channel_id": channel.id},
        )

    async def _archive(
        self,
        guild: discord.Guild,
        settings: PartnershipSettings,
        record: Partnership,
        channel: discord.abc.GuildChannel,
    ) -> None:
        category = await self._ensure_archive_category(guild, settings)

        if category is not None and channel.category_id != category.id:
            try:
                await channel.edit(category=category, reason="Parceria: cargo removido")
            except discord.HTTPException:
                logger.exception("Falha ao mover canal de parceria %s pra categoria de arquivamento.", channel.id)

        dedicated_role = guild.get_role(record.role_id) if record.role_id else None
        partner_role_id, streamer_role_id = await self.get_partner_role_ids(guild.id)
        await self._apply_overwrites(
            channel, guild, settings, partner_role_id, streamer_role_id, dedicated_role, readonly=True
        )

        now = datetime.now(UTC)
        async with self._database.session() as session:
            repo = PartnershipRepository(session)
            db_record = await repo.get_by_id(record.id)
            assert db_record is not None
            db_record.archived_at = now
            await session.flush()

        await self._record_audit(
            guild_id=guild.id, action="Canal movido", target_id=record.owner_id,
            details={"channel_id": channel.id, "categoria": ARCHIVE_CATEGORY_NAME},
        )
        await self._record_audit(
            guild_id=guild.id, action="Permissões alteradas", target_id=record.owner_id,
            details={"channel_id": channel.id, "motivo": "cargo removido"},
        )

    async def _delete_channel_and_role(
        self, guild: discord.Guild, record: Partnership, channel: discord.abc.GuildChannel
    ) -> None:
        try:
            await channel.delete(reason="Parceria: cargo removido (excluir canal configurado)")
        except discord.HTTPException:
            logger.warning("Falha ao apagar canal de parceria %s.", channel.id)

        if record.role_id is not None:
            role = guild.get_role(record.role_id)
            if role is not None:
                try:
                    await role.delete(reason="Parceria: cargo removido")
                except discord.HTTPException:
                    logger.warning("Falha ao apagar cargo dedicado de parceria %s.", record.role_id)

        await self._delete_record(record.id)
        await self._record_audit(
            guild_id=guild.id, action="Canal excluído", target_id=record.owner_id,
            details={"channel_id": channel.id},
        )

    async def _ensure_archive_category(
        self, guild: discord.Guild, settings: PartnershipSettings
    ) -> discord.CategoryChannel | None:
        candidate = self._resolve_category(guild, settings.archive_category_id)
        if candidate is not None:
            return candidate

        try:
            category = await guild.create_category(
                ARCHIVE_CATEGORY_NAME, reason="Parceria: categoria de arquivamento"
            )
        except discord.HTTPException:
            logger.exception("Falha ao criar categoria '%s' na guild %s.", ARCHIVE_CATEGORY_NAME, guild.id)
            return None

        await self.update_settings(guild.id, archive_category_id=category.id)
        await self._record_audit(
            guild_id=guild.id, action="Categoria criada", details={"nome": category.name, "categoria_id": category.id},
        )
        return category

    def _resolve_category(self, guild: discord.Guild, category_id: int | None) -> discord.CategoryChannel | None:
        if category_id is None:
            return None
        candidate = guild.get_channel(category_id)
        return candidate if isinstance(candidate, discord.CategoryChannel) else None

    def _build_overwrites(
        self,
        guild: discord.Guild,
        settings: PartnershipSettings,
        partner_role_id: int | None,
        streamer_role_id: int | None,
        dedicated_role: discord.Role | None,
        *,
        readonly: bool,
    ) -> dict[discord.Role, discord.PermissionOverwrite]:
        overwrites: dict[discord.Role, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True, send_messages=False, read_message_history=True
            ),
        }
        for role_id in {settings.staff_role_id, partner_role_id, streamer_role_id}:
            role = guild.get_role(role_id) if role_id else None
            if role is None:
                continue
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=not readonly, read_message_history=True
            )
        if dedicated_role is not None:
            overwrites[dedicated_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=not readonly, read_message_history=True
            )
        return overwrites

    async def _apply_overwrites(
        self,
        channel: discord.abc.GuildChannel,
        guild: discord.Guild,
        settings: PartnershipSettings,
        partner_role_id: int | None,
        streamer_role_id: int | None,
        dedicated_role: discord.Role | None,
        *,
        readonly: bool,
    ) -> None:
        overwrites = self._build_overwrites(guild, settings, partner_role_id, streamer_role_id, dedicated_role, readonly=readonly)
        try:
            await channel.edit(overwrites=overwrites, reason="Parceria: permissões sincronizadas")
        except discord.HTTPException:
            logger.exception("Falha ao sincronizar permissões do canal de parceria %s.", channel.id)

    async def _send_welcome_message(self, channel: discord.abc.Messageable, settings: PartnershipSettings) -> None:
        from views.partnership_view import PartnershipInfoView

        content = settings.welcome_message or DEFAULT_WELCOME_MESSAGE
        try:
            message = await channel.send(content=content, view=PartnershipInfoView())
            await message.pin(reason="Parceria: mensagem de boas-vindas fixada")
        except discord.HTTPException:
            logger.exception("Falha ao enviar/fixar mensagem de boas-vindas de parceria no canal %s.", channel.id)

    async def _delete_record(self, partnership_id: object) -> None:
        async with self._database.session() as session:
            repo = PartnershipRepository(session)
            record = await repo.get_by_id(partnership_id)
            if record is not None:
                await repo.delete(record)

    # --- auditoria -----------------------------------------------------------

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
