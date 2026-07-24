from __future__ import annotations

import discord
from discord.ext import commands

from core.bot import LimerenceBot
from database.models.audit_log import AuditLogCategory


class AuditLogsCog(commands.Cog):
    """Escuta eventos do Discord e audit logs, e manda tudo pro AuditLogService."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    async def _enabled(self, guild_id: int, category: AuditLogCategory) -> bool:
        settings = await self.bot.audit_log_service.get_settings(guild_id)
        return bool(getattr(settings, category.value))

    # --- Bans -----------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User | discord.Member) -> None:
        if not await self._enabled(guild.id, AuditLogCategory.BAN):
            return
        entry = await self.bot.audit_log_service.resolve_executor(
            guild, discord.AuditLogAction.ban, target_id=user.id
        )
        await self.bot.audit_log_service.record(
            guild_id=guild.id,
            category=AuditLogCategory.BAN,
            action="Banido",
            executor_id=entry.user_id if entry else None,
            executor_name=str(entry.user) if entry and entry.user else None,
            target_id=user.id,
            target_name=str(user),
            reason=entry.reason if entry else None,
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        if not await self._enabled(guild.id, AuditLogCategory.BAN):
            return
        entry = await self.bot.audit_log_service.resolve_executor(
            guild, discord.AuditLogAction.unban, target_id=user.id
        )
        await self.bot.audit_log_service.record(
            guild_id=guild.id,
            category=AuditLogCategory.BAN,
            action="Desbanido",
            executor_id=entry.user_id if entry else None,
            executor_name=str(entry.user) if entry and entry.user else None,
            target_id=user.id,
            target_name=str(user),
        )

    # --- Kick (detectado via audit log no on_member_remove) --------------------

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if not await self._enabled(member.guild.id, AuditLogCategory.KICK):
            return
        entry = await self.bot.audit_log_service.resolve_executor(
            member.guild, discord.AuditLogAction.kick, target_id=member.id
        )
        if entry is None:
            return  # saiu sozinho, nao foi kick
        await self.bot.audit_log_service.record(
            guild_id=member.guild.id,
            category=AuditLogCategory.KICK,
            action="Expulso",
            executor_id=entry.user_id,
            executor_name=str(entry.user) if entry.user else None,
            target_id=member.id,
            target_name=str(member),
            reason=entry.reason,
        )

    # --- Timeout, nickname, cargos (tudo via on_member_update) ------------------

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        guild = after.guild

        if before.timed_out_until != after.timed_out_until:
            if await self._enabled(guild.id, AuditLogCategory.TIMEOUT):
                entry = await self.bot.audit_log_service.resolve_executor(
                    guild, discord.AuditLogAction.member_update, target_id=after.id
                )
                if after.timed_out_until is not None:
                    await self.bot.audit_log_service.record(
                        guild_id=guild.id,
                        category=AuditLogCategory.TIMEOUT,
                        action="Timeout aplicado",
                        executor_id=entry.user_id if entry else None,
                        executor_name=str(entry.user) if entry and entry.user else None,
                        target_id=after.id,
                        target_name=str(after),
                        reason=entry.reason if entry else None,
                        details={"ate": discord.utils.format_dt(after.timed_out_until, style="F")},
                    )
                else:
                    await self.bot.audit_log_service.record(
                        guild_id=guild.id,
                        category=AuditLogCategory.TIMEOUT,
                        action="Timeout removido",
                        executor_id=entry.user_id if entry else None,
                        executor_name=str(entry.user) if entry and entry.user else None,
                        target_id=after.id,
                        target_name=str(after),
                    )

        if before.nick != after.nick:
            if await self._enabled(guild.id, AuditLogCategory.NICKNAME):
                entry = await self.bot.audit_log_service.resolve_executor(
                    guild, discord.AuditLogAction.member_update, target_id=after.id
                )
                await self.bot.audit_log_service.record(
                    guild_id=guild.id,
                    category=AuditLogCategory.NICKNAME,
                    action="Apelido alterado",
                    executor_id=entry.user_id if entry else None,
                    executor_name=str(entry.user) if entry and entry.user else None,
                    target_id=after.id,
                    target_name=str(after),
                    details={"antes": before.nick or before.name, "depois": after.nick or after.name},
                )

        before_roles = set(before.roles)
        after_roles = set(after.roles)
        if before_roles != after_roles and await self._enabled(guild.id, AuditLogCategory.ROLE_UPDATE):
            entry = await self.bot.audit_log_service.resolve_executor(
                guild, discord.AuditLogAction.member_role_update, target_id=after.id
            )
            added = after_roles - before_roles
            removed = before_roles - after_roles
            details: dict[str, object] = {}
            if added:
                details["adicionado"] = ", ".join(role.name for role in added)
            if removed:
                details["removido"] = ", ".join(role.name for role in removed)
            await self.bot.audit_log_service.record(
                guild_id=guild.id,
                category=AuditLogCategory.ROLE_UPDATE,
                action="Cargos do membro alterados",
                executor_id=entry.user_id if entry else None,
                executor_name=str(entry.user) if entry and entry.user else None,
                target_id=after.id,
                target_name=str(after),
                reason=entry.reason if entry else None,
                details=details,
            )

    # --- Bots adicionados (via on_member_join) ---------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not member.bot:
            return
        if not await self._enabled(member.guild.id, AuditLogCategory.BOT_ADDED):
            return
        entry = await self.bot.audit_log_service.resolve_executor(
            member.guild, discord.AuditLogAction.bot_add, target_id=member.id
        )
        await self.bot.audit_log_service.record(
            guild_id=member.guild.id,
            category=AuditLogCategory.BOT_ADDED,
            action="Bot adicionado",
            executor_id=entry.user_id if entry else None,
            executor_name=str(entry.user) if entry and entry.user else None,
            target_id=member.id,
            target_name=str(member),
        )

    # --- Canais e categorias -----------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        if not await self._enabled(channel.guild.id, AuditLogCategory.CHANNEL_CREATE_DELETE):
            return
        entry = await self.bot.audit_log_service.resolve_executor(
            channel.guild, discord.AuditLogAction.channel_create, target_id=channel.id
        )
        await self.bot.audit_log_service.record(
            guild_id=channel.guild.id,
            category=AuditLogCategory.CHANNEL_CREATE_DELETE,
            action="Canal criado",
            executor_id=entry.user_id if entry else None,
            executor_name=str(entry.user) if entry and entry.user else None,
            target_id=channel.id,
            target_name=channel.name,
            details={
                "categoria": channel.category.name if channel.category else "—",
                "tipo": str(channel.type),
            },
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        if not await self._enabled(channel.guild.id, AuditLogCategory.CHANNEL_CREATE_DELETE):
            return
        entry = await self.bot.audit_log_service.resolve_executor(
            channel.guild, discord.AuditLogAction.channel_delete, target_id=channel.id
        )
        await self.bot.audit_log_service.record(
            guild_id=channel.guild.id,
            category=AuditLogCategory.CHANNEL_CREATE_DELETE,
            action="Canal removido",
            executor_id=entry.user_id if entry else None,
            executor_name=str(entry.user) if entry and entry.user else None,
            target_id=channel.id,
            target_name=channel.name,
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel
    ) -> None:
        guild = after.guild
        is_category = isinstance(after, discord.CategoryChannel)
        category = AuditLogCategory.CATEGORY_UPDATE if is_category else AuditLogCategory.CHANNEL_UPDATE

        changes: dict[str, object] = {}
        if before.name != after.name:
            changes["nome"] = f"{before.name} → {after.name}"
        if isinstance(before, discord.TextChannel) and isinstance(after, discord.TextChannel):
            if before.category != after.category:
                changes["categoria"] = (
                    f"{before.category.name if before.category else '—'} → "
                    f"{after.category.name if after.category else '—'}"
                )
            if before.slowmode_delay != after.slowmode_delay:
                changes["slowmode"] = f"{before.slowmode_delay}s → {after.slowmode_delay}s"
            if before.nsfw != after.nsfw:
                changes["nsfw"] = f"{before.nsfw} → {after.nsfw}"

        if changes and await self._enabled(guild.id, category):
            entry = await self.bot.audit_log_service.resolve_executor(
                guild, discord.AuditLogAction.channel_update, target_id=after.id
            )
            await self.bot.audit_log_service.record(
                guild_id=guild.id,
                category=category,
                action="Categoria alterada" if is_category else "Canal alterado",
                executor_id=entry.user_id if entry else None,
                executor_name=str(entry.user) if entry and entry.user else None,
                target_id=after.id,
                target_name=after.name,
                reason=entry.reason if entry else None,
                details=changes,
            )

        if before.overwrites != after.overwrites and await self._enabled(
            guild.id, AuditLogCategory.PERMISSION_UPDATE
        ):
            entry = await self.bot.audit_log_service.resolve_executor(
                guild, discord.AuditLogAction.overwrite_update, target_id=after.id
            )
            await self.bot.audit_log_service.record(
                guild_id=guild.id,
                category=AuditLogCategory.PERMISSION_UPDATE,
                action="Permissões de canal alteradas",
                executor_id=entry.user_id if entry else None,
                executor_name=str(entry.user) if entry and entry.user else None,
                target_id=after.id,
                target_name=after.name,
                reason=entry.reason if entry else None,
            )

    # --- Cargos ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        if not await self._enabled(role.guild.id, AuditLogCategory.ROLE_CREATE_DELETE):
            return
        entry = await self.bot.audit_log_service.resolve_executor(
            role.guild, discord.AuditLogAction.role_create, target_id=role.id
        )
        await self.bot.audit_log_service.record(
            guild_id=role.guild.id,
            category=AuditLogCategory.ROLE_CREATE_DELETE,
            action="Cargo criado",
            executor_id=entry.user_id if entry else None,
            executor_name=str(entry.user) if entry and entry.user else None,
            target_id=role.id,
            target_name=role.name,
            details={"cor": str(role.color), "permissoes": str(role.permissions.value)},
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        if not await self._enabled(role.guild.id, AuditLogCategory.ROLE_CREATE_DELETE):
            return
        entry = await self.bot.audit_log_service.resolve_executor(
            role.guild, discord.AuditLogAction.role_delete, target_id=role.id
        )
        await self.bot.audit_log_service.record(
            guild_id=role.guild.id,
            category=AuditLogCategory.ROLE_CREATE_DELETE,
            action="Cargo removido",
            executor_id=entry.user_id if entry else None,
            executor_name=str(entry.user) if entry and entry.user else None,
            target_id=role.id,
            target_name=role.name,
        )

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        if not await self._enabled(after.guild.id, AuditLogCategory.ROLE_UPDATE):
            return
        changes: dict[str, object] = {}
        if before.name != after.name:
            changes["nome"] = f"{before.name} → {after.name}"
        if before.color != after.color:
            changes["cor"] = f"{before.color} → {after.color}"
        if before.permissions != after.permissions:
            changes["permissoes"] = f"{before.permissions.value} → {after.permissions.value}"
        if not changes:
            return
        entry = await self.bot.audit_log_service.resolve_executor(
            after.guild, discord.AuditLogAction.role_update, target_id=after.id
        )
        await self.bot.audit_log_service.record(
            guild_id=after.guild.id,
            category=AuditLogCategory.ROLE_UPDATE,
            action="Cargo alterado",
            executor_id=entry.user_id if entry else None,
            executor_name=str(entry.user) if entry and entry.user else None,
            target_id=after.id,
            target_name=after.name,
            reason=entry.reason if entry else None,
            details=changes,
        )

    # --- Mensagens ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        if not await self._enabled(message.guild.id, AuditLogCategory.MESSAGE_DELETE):
            return
        entry = await self.bot.audit_log_service.resolve_executor(
            message.guild, discord.AuditLogAction.message_delete, target_id=message.author.id
        )
        details: dict[str, object] = {"canal": message.channel.mention if hasattr(message.channel, "mention") else str(message.channel)}
        if message.content:
            details["conteudo"] = message.content[:500]
        if message.attachments:
            details["anexos"] = ", ".join(a.url for a in message.attachments)
        await self.bot.audit_log_service.record(
            guild_id=message.guild.id,
            category=AuditLogCategory.MESSAGE_DELETE,
            action="Mensagem apagada",
            executor_id=entry.user_id if entry else None,
            executor_name=str(entry.user) if entry and entry.user else "Autor (auto-exclusão)",
            target_id=message.author.id,
            target_name=str(message.author),
            details=details,
        )

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]) -> None:
        if not messages or messages[0].guild is None:
            return
        guild = messages[0].guild
        if not await self._enabled(guild.id, AuditLogCategory.BULK_DELETE):
            return
        entry = await self.bot.audit_log_service.resolve_executor(
            guild, discord.AuditLogAction.message_bulk_delete, target_id=messages[0].channel.id
        )
        channel = messages[0].channel
        await self.bot.audit_log_service.record(
            guild_id=guild.id,
            category=AuditLogCategory.BULK_DELETE,
            action="Bulk delete",
            executor_id=entry.user_id if entry else None,
            executor_name=str(entry.user) if entry and entry.user else None,
            target_id=channel.id,
            target_name=channel.name if hasattr(channel, "name") else str(channel),
            details={"quantidade": len(messages)},
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if after.guild is None or after.author.bot or before.content == after.content:
            return
        if not await self._enabled(after.guild.id, AuditLogCategory.MESSAGE_EDIT):
            return
        await self.bot.audit_log_service.record(
            guild_id=after.guild.id,
            category=AuditLogCategory.MESSAGE_EDIT,
            action="Mensagem editada",
            executor_id=after.author.id,
            executor_name=str(after.author),
            target_id=after.author.id,
            target_name=str(after.author),
            details={
                "canal": after.channel.mention if hasattr(after.channel, "mention") else str(after.channel),
                "antes": (before.content or "—")[:400],
                "depois": (after.content or "—")[:400],
            },
        )

    # --- Voz ---------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        guild = member.guild

        if before.channel != after.channel:
            if before.channel is None and after.channel is not None:
                if await self._enabled(guild.id, AuditLogCategory.VOICE_JOIN_LEAVE):
                    await self.bot.audit_log_service.record(
                        guild_id=guild.id,
                        category=AuditLogCategory.VOICE_JOIN_LEAVE,
                        action="Entrou na call",
                        executor_id=member.id,
                        executor_name=str(member),
                        target_id=member.id,
                        target_name=str(member),
                        details={"canal": after.channel.name},
                    )
            elif before.channel is not None and after.channel is None:
                if await self._enabled(guild.id, AuditLogCategory.VOICE_JOIN_LEAVE):
                    entry = await self.bot.audit_log_service.resolve_executor(
                        guild, discord.AuditLogAction.member_disconnect, target_id=member.id
                    )
                    await self.bot.audit_log_service.record(
                        guild_id=guild.id,
                        category=AuditLogCategory.VOICE_JOIN_LEAVE,
                        action="Foi desconectado da call" if entry else "Saiu da call",
                        executor_id=entry.user_id if entry else member.id,
                        executor_name=(str(entry.user) if entry and entry.user else str(member)),
                        target_id=member.id,
                        target_name=str(member),
                        details={"canal": before.channel.name},
                    )
            else:
                if await self._enabled(guild.id, AuditLogCategory.VOICE_MOVE):
                    entry = await self.bot.audit_log_service.resolve_executor(
                        guild, discord.AuditLogAction.member_move, target_id=member.id
                    )
                    await self.bot.audit_log_service.record(
                        guild_id=guild.id,
                        category=AuditLogCategory.VOICE_MOVE,
                        action="Foi movido de call" if entry else "Mudou de call",
                        executor_id=entry.user_id if entry else member.id,
                        executor_name=(str(entry.user) if entry and entry.user else str(member)),
                        target_id=member.id,
                        target_name=str(member),
                        details={
                            "de": before.channel.name if before.channel else "—",
                            "para": after.channel.name if after.channel else "—",
                        },
                    )

        if before.mute != after.mute and await self._enabled(guild.id, AuditLogCategory.MUTE_UNMUTE):
            entry = await self.bot.audit_log_service.resolve_executor(
                guild, discord.AuditLogAction.member_update, target_id=member.id
            )
            await self.bot.audit_log_service.record(
                guild_id=guild.id,
                category=AuditLogCategory.MUTE_UNMUTE,
                action="Mutado" if after.mute else "Desmutado",
                executor_id=entry.user_id if entry else None,
                executor_name=str(entry.user) if entry and entry.user else None,
                target_id=member.id,
                target_name=str(member),
            )

        if before.deaf != after.deaf and await self._enabled(guild.id, AuditLogCategory.DEAF_UNDEAF):
            entry = await self.bot.audit_log_service.resolve_executor(
                guild, discord.AuditLogAction.member_update, target_id=member.id
            )
            await self.bot.audit_log_service.record(
                guild_id=guild.id,
                category=AuditLogCategory.DEAF_UNDEAF,
                action="Ensurdecido" if after.deaf else "Deaf removido",
                executor_id=entry.user_id if entry else None,
                executor_name=str(entry.user) if entry and entry.user else None,
                target_id=member.id,
                target_name=str(member),
            )

    # --- Emojis e stickers -----------------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_emojis_update(
        self,
        guild: discord.Guild,
        before: list[discord.Emoji],
        after: list[discord.Emoji],
    ) -> None:
        if not await self._enabled(guild.id, AuditLogCategory.EMOJI):
            return
        before_ids = {e.id for e in before}
        after_ids = {e.id for e in after}
        for emoji in after:
            if emoji.id not in before_ids:
                await self.bot.audit_log_service.record(
                    guild_id=guild.id,
                    category=AuditLogCategory.EMOJI,
                    action="Emoji criado",
                    target_id=emoji.id,
                    target_name=emoji.name,
                )
        for emoji in before:
            if emoji.id not in after_ids:
                await self.bot.audit_log_service.record(
                    guild_id=guild.id,
                    category=AuditLogCategory.EMOJI,
                    action="Emoji removido",
                    target_id=emoji.id,
                    target_name=emoji.name,
                )

    @commands.Cog.listener()
    async def on_guild_stickers_update(
        self,
        guild: discord.Guild,
        before: list[discord.GuildSticker],
        after: list[discord.GuildSticker],
    ) -> None:
        if not await self._enabled(guild.id, AuditLogCategory.STICKER):
            return
        before_ids = {s.id for s in before}
        after_ids = {s.id for s in after}
        for sticker in after:
            if sticker.id not in before_ids:
                await self.bot.audit_log_service.record(
                    guild_id=guild.id,
                    category=AuditLogCategory.STICKER,
                    action="Sticker criado",
                    target_id=sticker.id,
                    target_name=sticker.name,
                )
        for sticker in before:
            if sticker.id not in after_ids:
                await self.bot.audit_log_service.record(
                    guild_id=guild.id,
                    category=AuditLogCategory.STICKER,
                    action="Sticker removido",
                    target_id=sticker.id,
                    target_name=sticker.name,
                )

    # --- Configuração do servidor -----------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild) -> None:
        if not await self._enabled(after.id, AuditLogCategory.SERVER_CONFIG):
            return
        changes: dict[str, object] = {}
        if before.name != after.name:
            changes["nome"] = f"{before.name} → {after.name}"
        if before.icon != after.icon:
            changes["icone"] = "alterado"
        if before.banner != after.banner:
            changes["banner"] = "alterado"
        if before.description != after.description:
            changes["descricao"] = f"{before.description or '—'} → {after.description or '—'}"
        if before.verification_level != after.verification_level:
            changes["nivel_verificacao"] = f"{before.verification_level} → {after.verification_level}"
        if not changes:
            return
        entry = await self.bot.audit_log_service.resolve_executor(
            after, discord.AuditLogAction.guild_update
        )
        await self.bot.audit_log_service.record(
            guild_id=after.id,
            category=AuditLogCategory.SERVER_CONFIG,
            action="Configuração do servidor alterada",
            executor_id=entry.user_id if entry else None,
            executor_name=str(entry.user) if entry and entry.user else None,
            details=changes,
        )


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(AuditLogsCog(bot))
