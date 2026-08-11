from __future__ import annotations

from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.bot import LimerenceBot
from core.logger import get_logger
from database.models.audit_log import AuditLogCategory
from database.models.guild_settings import GuildSettings
from database.models.punishment import APPEALABLE_TYPES, PunishmentStatus, PunishmentType
from database.models.punishment_appeal import AppealMethod
from services.punishment_service import AppealError, PunishmentError
from utils.appeal_dm import DMAppealRateLimiter, parse_recorrer_dm_command
from utils.checks import (
    can_punish_target,
    is_staff,
    member_can,
    member_can_apply_punishment,
    member_is_owner_or_ceo,
)
from utils.time import InvalidDurationError, humanize_duration, parse_duration
from views.appeal_view import punishment_dm_view, send_appeal_to_review_channel
from views.embeds import (
    appeal_denied_dm_embed,
    punishment_confirm_embed,
    punishment_dm_embed,
    punishment_dm_failed_embed,
    punishment_dm_notified_embed,
    punishment_history_embed,
    punishment_log_embed,
    punishment_review_dm_embed,
    punishment_revoked_log_embed,
    punishment_status_embed,
)
from views.pending_punishments_view import build_panel
from views.punishment_confirmation_view import PunishmentConfirmView
from views.punishment_execute_view import ConfirmView, PunishmentExecuteView

logger = get_logger("moderation")

_TYPE_CHOICES = [
    app_commands.Choice(name="Ban", value=PunishmentType.BAN.value),
    app_commands.Choice(name="Ban Temporário", value=PunishmentType.BAN_TEMPORARIO.value),
    app_commands.Choice(name="Timeout/Mute", value=PunishmentType.TIMEOUT.value),
    app_commands.Choice(name="Kick", value=PunishmentType.KICK.value),
    app_commands.Choice(name="Advertência", value=PunishmentType.ADVERTENCIA.value),
]

_TYPES_REQUIRING_DURATION = {PunishmentType.BAN_TEMPORARIO, PunishmentType.TIMEOUT}


async def _validate_punishment(
    interaction: discord.Interaction,
    settings: GuildSettings,
    *,
    staff: discord.Member,
    target: discord.Member,
    ptype: PunishmentType,
    reason: str,
    proofs: list[str],
) -> str | None:
    """Etapa 3: validacoes antes de criar a punicao. Retorna a mensagem de erro,
    ou None se tudo passou."""
    if not await member_can_apply_punishment(interaction, ptype):
        return "Você não possui permissão para aplicar esse tipo de punição."
    if not can_punish_target(staff, target):
        return "Você não possui permissão para punir este usuário (hierarquia de cargos)."
    if not reason.strip():
        return "Motivo não pode ficar vazio."
    if settings.require_proof and not proofs:
        return "É obrigatório enviar provas (anexo ou link) para aplicar uma punição."
    if interaction.guild is not None and interaction.guild.get_member(target.id) is None:
        return "Usuário não está mais no servidor."
    return None


class ModerationCog(commands.Cog):
    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self._dm_appeal_limiter = DMAppealRateLimiter()
        self.review_expiration_task.start()

    def cog_unload(self) -> None:
        self.review_expiration_task.cancel()

    @tasks.loop(minutes=1)
    async def review_expiration_task(self) -> None:
        """Etapa 22: aplica a punição real automaticamente quando o prazo de análise
        expira sem o usuário recorrer (ou sem a staff decidir um recurso já enviado)."""
        for punishment in await self.bot.punishment_service.list_expired_pending_reviews():
            guild = self.bot.get_guild(punishment.guild_id)
            if guild is None:
                continue

            pending_appeal = await self.bot.punishment_service.get_pending_appeal(punishment.id)
            if pending_appeal is not None:
                # ja tem recurso aguardando decisao da staff — nao expira por baixo, staff decide.
                continue

            settings = await self.bot.config_service.get_settings(guild.id)
            try:
                punishment = await self.bot.punishment_service.resolve_review(
                    guild=guild,
                    punishment_id=punishment.id,
                    approved=False,
                    reviewer_id=None,
                    reviewer_name="Sistema (expiração automática)",
                    reason="Prazo de recurso expirado sem resposta.",
                    review_role_id=settings.review_role_id,
                )
            except PunishmentError as exc:
                logger.warning(
                    "Falha ao expirar análise da punição %s: %s", punishment.punishment_code, exc
                )
                continue

            await self.bot.audit_log_service.record(
                guild_id=guild.id,
                category=AuditLogCategory.PUNISHMENT_REVIEW,
                action="BAN_APPLIED_AFTER_REVIEW",
                executor_name="Sistema (expiração automática)",
                target_id=punishment.user_id,
                target_name=punishment.user_name,
                reason="Prazo de recurso expirado sem resposta.",
                details={"punishment_code": punishment.punishment_code},
            )

            if settings.log_punishments_channel_id is not None:
                log_channel = guild.get_channel(settings.log_punishments_channel_id)
                if isinstance(log_channel, discord.abc.Messageable):
                    await log_channel.send(embed=punishment_log_embed(punishment))

            user = guild.get_member(punishment.user_id) or self.bot.get_user(punishment.user_id)
            if user is not None:
                try:
                    await user.send(
                        embed=appeal_denied_dm_embed(
                            "Prazo de recurso expirado sem resposta.", "Sistema (expiração automática)"
                        )
                    )
                except discord.HTTPException:
                    pass

    @review_expiration_task.before_loop
    async def _before_review_expiration_task(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Isolamento automático: sempre que alguém receber o cargo configurado em
        'Cargo Em Análise' (/config → Moderação), por qualquer meio — atribuição manual
        da staff ou via /punir —, perde todos os outros cargos na hora."""
        if before.roles == after.roles:
            return
        added_role_ids = {r.id for r in after.roles} - {r.id for r in before.roles}
        if not added_role_ids:
            return

        settings = await self.bot.config_service.get_settings(after.guild.id)
        review_role_id = settings.review_role_id
        if review_role_id is None or review_role_id not in added_role_ids:
            return

        other_roles = [
            role for role in after.roles
            if role.id not in (review_role_id, after.guild.default_role.id)
        ]
        if not other_roles:
            return
        try:
            await after.remove_roles(
                *other_roles, reason="Isolamento automático: cargo de análise atribuído"
            )
        except discord.Forbidden:
            logger.warning(
                "Sem permissão pra isolar %s automaticamente (guild %s).", after.id, after.guild.id
            )
        except discord.HTTPException as exc:
            logger.warning("Falha ao isolar %s automaticamente: %s", after.id, exc)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Devolve o cargo de jogador (/config → Cargos) se o usuário teve um ban
        revogado antes de reentrar — banimento de verdade tira o membro da guild, então
        so da pra restaurar o cargo quando ele volta."""
        settings = await self.bot.config_service.get_settings(member.guild.id)
        await self.bot.punishment_service.restore_player_role_on_rejoin(
            member=member, player_role_id=settings.player_role_id
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Fallback de recurso por texto na DM (`!recorrer CODIGO motivo`) — usado quando
        o botão/modal de recurso falha por perda de contexto de guild (ex.: usuário banido)."""
        if message.author.bot or message.guild is not None:
            return

        parsed = parse_recorrer_dm_command(message.content)
        if parsed is None:
            return

        if not self._dm_appeal_limiter.allow(message.author.id):
            logger.warning("Rate limit de !recorrer atingido para user_id=%s", message.author.id)
            return

        code, motivo = parsed
        punishment = await self.bot.punishment_service.find_by_code(code)
        if punishment is None:
            logger.info("!recorrer com código inexistente: %s (user_id=%s)", code, message.author.id)
            await message.channel.send("❌ Não encontrei essa punição.\nVerifique o ID informado.")
            return
        if punishment.user_id != message.author.id:
            logger.warning(
                "!recorrer de outro usuário: code=%s user_id=%s dono=%s",
                code, message.author.id, punishment.user_id,
            )
            await message.channel.send("❌ Você não pode recorrer dessa punição.")
            return

        try:
            appeal = await self.bot.punishment_service.submit_appeal(
                punishment_id=punishment.id,
                user_id=message.author.id,
                message=motivo,
                additional_info=None,
                method=AppealMethod.DM_MESSAGE,
            )
        except AppealError as exc:
            logger.info("!recorrer rejeitado: code=%s user_id=%s erro=%s", code, message.author.id, exc)
            await message.channel.send(f"❌ {exc}")
            return

        await message.channel.send(
            "✅ Recurso enviado! A staff vai analisar e você será notificado por aqui."
        )
        await send_appeal_to_review_channel(self.bot, appeal, executor_name=str(message.author))

    @app_commands.command(name="punir", description="Aplica uma punição a um membro.")
    @app_commands.describe(
        usuario="Membro que receberá a punição",
        tipo="Tipo de punição",
        motivo="Motivo da punição",
        provas="Anexo (imagem/vídeo) como prova",
        provas_link="Link como prova (use se não for anexar um arquivo)",
        duracao="Duração — obrigatório para ban_temporario e timeout (ex.: 24h, 30m)",
    )
    @app_commands.choices(tipo=_TYPE_CHOICES)
    async def punir(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        tipo: app_commands.Choice[str],
        motivo: str,
        provas: discord.Attachment | None = None,
        provas_link: str | None = None,
        duracao: str | None = None,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        staff = interaction.user
        ptype = PunishmentType(tipo.value)

        if usuario.id == staff.id:
            await interaction.followup.send("Você não pode punir a si mesmo.", ephemeral=True)
            return
        if usuario.bot:
            await interaction.followup.send("Não é possível punir um bot.", ephemeral=True)
            return

        settings = await self.bot.config_service.get_settings(guild.id)
        if not settings.moderation_enabled:
            await interaction.followup.send(
                "O sistema de moderação está desativado neste servidor.", ephemeral=True
            )
            return

        proofs: list[str] = []
        if provas is not None:
            proofs.append(provas.url)
        if provas_link:
            proofs.append(provas_link)

        duration: timedelta | None = None
        if duracao is not None:
            try:
                duration = parse_duration(duracao)
            except InvalidDurationError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
        if ptype in _TYPES_REQUIRING_DURATION and duration is None:
            await interaction.followup.send(
                "Duração é obrigatória para esse tipo de punição (ex.: 24h, 30m).", ephemeral=True
            )
            return

        # Etapa 22: se a guild configurou cargo de analise, esse tipo de punicao passa
        # pelo fluxo de isolamento (recurso antes do ban definitivo) em vez do fluxo antigo.
        use_review_flow = settings.review_role_id is not None and ptype in APPEALABLE_TYPES

        # Etapa 2: primeira confirmacao — so uma revisao, nada e persistido ainda.
        confirm_view = PunishmentConfirmView(staff.id)
        await interaction.followup.send(
            embed=punishment_confirm_embed(
                user=usuario,
                ptype=ptype,
                duration_label=duracao if duration else None,
                reason=motivo,
                proofs=proofs,
                staff_name=str(staff),
                is_review=use_review_flow,
            ),
            view=confirm_view,
            ephemeral=True,
        )
        await confirm_view.wait()
        if not confirm_view.confirmed:
            return

        # Etapa 3: validacoes de negocio.
        error = await _validate_punishment(
            interaction, settings, staff=staff, target=usuario, ptype=ptype, reason=motivo, proofs=proofs
        )
        if error is not None:
            await interaction.followup.send(
                f"❌ Não foi possível continuar com essa punição.\n{error}", ephemeral=True
            )
            return

        max_timeout = (
            timedelta(minutes=settings.max_timeout_duration_minutes)
            if settings.max_timeout_duration_minutes
            else None
        )

        if use_review_flow:
            await self._punir_com_analise(
                interaction,
                guild=guild,
                staff=staff,
                usuario=usuario,
                ptype=ptype,
                motivo=motivo,
                proofs=proofs,
                duration=duration,
                max_timeout=max_timeout,
                settings=settings,
            )
            return

        try:
            punishment = await self.bot.punishment_service.create_pending(
                guild=guild,
                staff=staff,
                target=usuario,
                ptype=ptype,
                reason=motivo,
                proofs=proofs,
                duration=duration,
                max_timeout=max_timeout,
            )
        except PunishmentError as exc:
            await interaction.followup.send(
                f"❌ Não foi possível continuar com essa punição.\n{exc}", ephemeral=True
            )
            return

        # Etapa 4: tenta notificar o usuario por DM ANTES de aplicar a punicao de fato.
        dm_sent = False
        failure_reason: str | None = None
        try:
            view = punishment_dm_view(punishment.id) if punishment.type in APPEALABLE_TYPES else None
            await usuario.send(embed=punishment_dm_embed(punishment), view=view)
            dm_sent = True
        except discord.Forbidden:
            failure_reason = "Usuário bloqueou mensagens privadas ou não permite DM de membros do servidor."
        except discord.HTTPException as exc:
            failure_reason = f"Discord recusou a mensagem ({exc})."

        punishment = await self.bot.punishment_service.record_dm_result(
            punishment.id, sent=dm_sent, failure_reason=failure_reason
        )

        execute_view = PunishmentExecuteView(staff.id)
        result_embed = (
            punishment_dm_notified_embed()
            if dm_sent
            else punishment_dm_failed_embed(failure_reason or "Motivo desconhecido")
        )
        await interaction.followup.send(embed=result_embed, view=execute_view, ephemeral=True)
        await execute_view.wait()

        if not execute_view.confirmed:
            await self.bot.punishment_service.cancel_pending(punishment_id=punishment.id, staff=staff)
            await interaction.followup.send("Punição cancelada.", ephemeral=True)
            return

        # Etapa 5: anti-erro — reconfirma tudo de novo antes de aplicar de verdade.
        fresh_target = guild.get_member(usuario.id)
        if fresh_target is None:
            await self.bot.punishment_service.cancel_pending(punishment_id=punishment.id, staff=staff)
            await interaction.followup.send(
                "O usuário não está mais no servidor — punição cancelada.", ephemeral=True
            )
            return
        if not await member_can_apply_punishment(interaction, ptype) or not can_punish_target(
            staff, fresh_target
        ):
            await self.bot.punishment_service.cancel_pending(punishment_id=punishment.id, staff=staff)
            await interaction.followup.send(
                "Permissão insuficiente no momento da aplicação — punição cancelada.", ephemeral=True
            )
            return

        try:
            punishment = await self.bot.punishment_service.apply_pending(
                guild=guild, punishment_id=punishment.id, target=fresh_target
            )
        except PunishmentError as exc:
            # nao deixa a punicao presa em PENDING/NOTIFIED — senao o anti-duplicacao
            # bloqueia pra sempre um novo /punir pro mesmo usuario/tipo.
            await self.bot.punishment_service.cancel_pending(
                punishment_id=punishment.id, staff=staff, reason=f"Falha ao aplicar: {exc}"
            )
            await interaction.followup.send(
                f"{exc}\n⚠️ A punição não foi aplicada e o registro foi liberado — corrija o problema "
                "(ex.: cargo do bot acima do cargo do usuário) e tente novamente.",
                ephemeral=True,
            )
            return

        if settings.log_punishments_channel_id is not None:
            log_channel = guild.get_channel(settings.log_punishments_channel_id)
            if isinstance(log_channel, discord.abc.Messageable):
                await log_channel.send(embed=punishment_log_embed(punishment))

        await interaction.followup.send(
            f"Punição **{punishment.punishment_code}** aplicada a {usuario.mention}.", ephemeral=True
        )

    async def _punir_com_analise(
        self,
        interaction: discord.Interaction,
        *,
        guild: discord.Guild,
        staff: discord.Member,
        usuario: discord.Member,
        ptype: PunishmentType,
        motivo: str,
        proofs: list[str],
        duration: timedelta | None,
        max_timeout: timedelta | None,
        settings: GuildSettings,
    ) -> None:
        """Etapa 22: fluxo de punicao com isolamento — usuario fica com cargo de analise
        e pode recorrer antes da acao real (ban/kick/timeout) ser aplicada de fato."""
        timeout_minutes = settings.review_timeout_minutes or 30
        try:
            punishment = await self.bot.punishment_service.create_pending_review(
                guild=guild,
                staff=staff,
                target=usuario,
                ptype=ptype,
                reason=motivo,
                proofs=proofs,
                duration=duration,
                max_timeout=max_timeout,
                review_timeout_minutes=timeout_minutes,
            )
        except PunishmentError as exc:
            await interaction.followup.send(
                f"❌ Não foi possível continuar com essa punição.\n{exc}", ephemeral=True
            )
            return

        await self.bot.audit_log_service.record(
            guild_id=guild.id,
            category=AuditLogCategory.PUNISHMENT_REVIEW,
            action="PUNISHMENT_PENDING_CREATED",
            executor_id=staff.id,
            executor_name=str(staff),
            target_id=usuario.id,
            target_name=str(usuario),
            reason=motivo,
            details={"punishment_code": punishment.punishment_code, "method": "BUTTON"},
        )

        try:
            await self.bot.punishment_service.isolate_member(
                guild=guild,
                punishment_id=punishment.id,
                member=usuario,
                review_role_id=settings.review_role_id,
            )
        except PunishmentError as exc:
            await interaction.followup.send(
                f"{exc}\n⚠️ A punição **{punishment.punishment_code}** foi criada mas o isolamento "
                "falhou — use /revogar_punicao se quiser cancelar.",
                ephemeral=True,
            )
            return

        await self.bot.audit_log_service.record(
            guild_id=guild.id,
            category=AuditLogCategory.PUNISHMENT_REVIEW,
            action="USER_ISOLATED",
            executor_id=staff.id,
            executor_name=str(staff),
            target_id=usuario.id,
            target_name=str(usuario),
            details={"punishment_code": punishment.punishment_code, "review_role_id": settings.review_role_id},
        )

        dm_sent = False
        try:
            view = punishment_dm_view(punishment.id)
            await usuario.send(embed=punishment_review_dm_embed(punishment), view=view)
            dm_sent = True
        except discord.HTTPException:
            pass

        if settings.log_punishments_channel_id is not None:
            log_channel = guild.get_channel(settings.log_punishments_channel_id)
            if isinstance(log_channel, discord.abc.Messageable):
                await log_channel.send(embed=punishment_log_embed(punishment))

        dm_note = "" if dm_sent else "\n⚠️ Não foi possível enviar a DM de aviso (recurso só via /recorrer se ele ainda tiver acesso ao servidor)."
        await interaction.followup.send(
            f"Punição **{punishment.punishment_code}** criada e usuário isolado para análise "
            f"(prazo de {timeout_minutes} min para recorrer).{dm_note}",
            ephemeral=True,
        )

    @app_commands.command(name="historico", description="Mostra o histórico de punições de um membro.")
    @app_commands.describe(usuario="Membro para consultar o histórico")
    @is_staff()
    async def historico(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        punishments = await self.bot.punishment_service.list_history(interaction.guild.id, usuario.id)
        await interaction.followup.send(
            embed=punishment_history_embed(usuario, punishments), ephemeral=True
        )

    @app_commands.command(name="punicao_ver", description="Mostra o status atual de uma punição.")
    @app_commands.describe(punicao="ID da punição (ex.: BAN-82931)")
    @is_staff()
    async def punicao_ver(self, interaction: discord.Interaction, punicao: str) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        punishment = await self.bot.punishment_service.get_by_code(
            interaction.guild.id, punicao.strip().upper()
        )
        if punishment is None:
            await interaction.followup.send("Punição não encontrada.", ephemeral=True)
            return

        time_remaining = None
        if punishment.status == PunishmentStatus.PENDING_REVIEW and punishment.review_deadline_at:
            remaining_seconds = (punishment.review_deadline_at - datetime.now(UTC)).total_seconds()
            time_remaining = humanize_duration(max(int(remaining_seconds), 0)) if remaining_seconds > 0 else "Expirado (aguardando processamento)"

        await interaction.followup.send(
            embed=punishment_status_embed(punishment, time_remaining=time_remaining), ephemeral=True
        )

    @app_commands.command(name="recorrer", description="Envia um recurso para uma punição que você recebeu.")
    @app_commands.describe(
        punicao="ID da punição (ex.: BAN-82931)", motivo="Explique por que a punição deveria ser removida"
    )
    async def recorrer(self, interaction: discord.Interaction, punicao: str, motivo: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if interaction.guild is None:
            await interaction.followup.send(
                "Use este comando dentro do servidor.", ephemeral=True
            )
            return
        guild = interaction.guild

        punishment = await self.bot.punishment_service.get_by_code(guild.id, punicao.strip().upper())
        if punishment is None:
            await interaction.followup.send("Punição não encontrada.", ephemeral=True)
            return

        try:
            appeal = await self.bot.punishment_service.submit_appeal(
                punishment_id=punishment.id,
                user_id=interaction.user.id,
                message=motivo,
                additional_info=None,
            )
        except AppealError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        await interaction.followup.send(
            "Recurso enviado! A staff vai analisar e você será notificado por DM.", ephemeral=True
        )
        await send_appeal_to_review_channel(self.bot, appeal, executor_name=str(interaction.user))

    @app_commands.command(name="revogar_punicao", description="Revoga uma punição aplicada anteriormente.")
    @app_commands.describe(punicao="ID da punição (ex.: BAN-82931)", motivo="Motivo da revogação")
    async def revogar_punicao(
        self, interaction: discord.Interaction, punicao: str, motivo: str
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        if not await member_is_owner_or_ceo(interaction):
            await interaction.response.send_message(
                "Apenas o Owner pode revogar punições.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        punishment = await self.bot.punishment_service.get_by_code(guild.id, punicao.strip().upper())
        if punishment is None:
            await interaction.followup.send("Punição não encontrada.", ephemeral=True)
            return

        confirm_view = ConfirmView(interaction.user.id)
        await interaction.followup.send(
            f"Revogar punição **{punishment.punishment_code}**?", view=confirm_view, ephemeral=True
        )
        await confirm_view.wait()
        if not confirm_view.confirmed:
            return

        try:
            punishment = await self.bot.punishment_service.revoke(
                guild=guild,
                punishment_id=punishment.id,
                revoked_by=interaction.user,
                reason=motivo,
            )
        except PunishmentError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        settings = await self.bot.config_service.get_settings(guild.id)
        if settings.log_punishments_channel_id is not None:
            log_channel = guild.get_channel(settings.log_punishments_channel_id)
            if isinstance(log_channel, discord.abc.Messageable):
                await log_channel.send(embed=punishment_revoked_log_embed(punishment, via_appeal=False))

        await interaction.followup.send(
            f"Punição **{punishment.punishment_code}** revogada.", ephemeral=True
        )

    @app_commands.command(
        name="analises", description="Mostra as punições atualmente em análise (aguardando recurso)."
    )
    @app_commands.describe(
        filtro="Filtrar por tipo de punição",
        staff="Mostrar somente punições aplicadas por este staff",
    )
    @app_commands.choices(
        filtro=[
            app_commands.Choice(name="Todos", value="todos"),
            app_commands.Choice(name="Ban", value="ban"),
            app_commands.Choice(name="Timeout", value="timeout"),
            app_commands.Choice(name="Kick", value="kick"),
            app_commands.Choice(name="Advertência", value="advertencia"),
        ]
    )
    async def analises(
        self,
        interaction: discord.Interaction,
        filtro: app_commands.Choice[str] | None = None,
        staff: discord.Member | None = None,
    ) -> None:
        if interaction.guild is None:
            return
        if not await member_can(interaction, "analises"):
            await interaction.response.send_message(
                "❌ Você não possui permissão para visualizar punições em análise.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        filtro_value = filtro.value if filtro else "todos"
        embed, view = await build_panel(
            self.bot, guild_id=interaction.guild.id, filtro=filtro_value, staff_id=staff.id if staff else 0, page=1
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        await self.bot.audit_log_service.record(
            guild_id=interaction.guild.id,
            category=AuditLogCategory.PUNISHMENT_REVIEW,
            action="VIEW_PENDING_PUNISHMENTS",
            executor_id=interaction.user.id,
            executor_name=str(interaction.user),
            details={"filtro": filtro_value, "staff_id": staff.id if staff else None},
        )


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(ModerationCog(bot))
