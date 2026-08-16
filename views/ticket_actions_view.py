from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import discord

from core.logger import get_logger
from database.models.audit_log import AuditLogCategory
from database.models.log import LogAction
from database.models.ticket import Ticket, TicketStatus
from database.models.ticket_panel import TicketPanel
from services.claim_service import ClaimError
from services.evaluation_service import normalize_evaluation_method
from services.ticket_panel_service import member_matches_panel_claim_roles
from services.ticket_service import TicketNotClaimedError, TicketNotFoundError
from utils.achievements import announce_achievements
from utils.checks import member_can, member_is_staff
from utils.constants import EMBED_COLOR_DEFAULT
from views.base_view import SafeView
from views.confirm_close_view import ConfirmCloseView
from views.dm_evaluation_view import DMEvaluationView
from views.embeds import (
    evaluation_dm_embed,
    ticket_closed_summary_embed,
    ticket_embed,
    ticket_panel_status_label,
)
from views.evaluation_view import EvaluationView
from views.ticket_closed_view import TicketClosedView, send_ticket_transcript

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("ticket_actions")


async def _deny_if_cant(
    interaction: discord.Interaction, action: str, *, already_deferred: bool = False
) -> bool:
    """`already_deferred` diz se o chamador ja deu `defer()` antes — nesse caso
    a recusa sai por `followup.send` em vez de `response.send_message`. Assumir
    e Liberar checam a permissao ANTES de deferir (comportamento original,
    inalterado); Fechar defere primeiro (nunca abre modal, e a checagem +
    get_by_channel_id ja eram feitas antes de qualquer resposta)."""
    if await member_can(interaction, action):
        return False
    if already_deferred:
        await interaction.followup.send(
            "Você não tem permissão para usar esse botão.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "Você não tem permissão para usar esse botão.", ephemeral=True
        )
    return True


async def _resolve_opener(
    bot: LimerenceBot, guild: discord.Guild, ticket: Ticket
) -> discord.Member | discord.User | None:
    opener = guild.get_member(ticket.opened_by_discord_id)
    if opener is not None:
        return opener
    try:
        return await bot.fetch_user(ticket.opened_by_discord_id)
    except discord.HTTPException:
        return None


_PANEL_NOT_PROVIDED: Any = object()


async def _refresh_panel_message(
    interaction: discord.Interaction,
    ticket: Ticket,
    *,
    claimed_staff_name: str | None,
    disabled: bool = False,
    panel: Any = _PANEL_NOT_PROVIDED,
) -> None:
    """Reedita a propria mensagem do painel (a que carrega os botoes) com o
    embed recalculado — Status/Assumido por/Aberto nunca ficam desatualizados
    depois de Assumir/Liberar/Incluir/Remover/Fechar. `interaction.message` e
    a mensagem do componente clicado, entao isso nao gasta nenhuma chamada
    extra de fetch_message.

    `panel`: se quem chamou ja buscou o painel do ticket por outro motivo na
    MESMA interacao (ex.: `claim()` ja busca pra checar `claim_role_ids`),
    passa aqui pra nao repetir a consulta — `panel_id` de um ticket nunca muda
    depois de criado, entao o painel buscado antes do claim/unclaim ainda vale
    depois. Sem passar nada, busca do jeito de sempre (comportamento
    inalterado pra quem nao tem o dado a mao, ex.: `close()`)."""
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    guild = interaction.guild
    message = interaction.message
    if guild is None or not isinstance(message, discord.Message):
        return
    opener = await _resolve_opener(bot, guild, ticket)
    if opener is None:
        return
    if panel is _PANEL_NOT_PROVIDED:
        panel = await bot.ticket_panel_service.get_panel_for_ticket(ticket)
    embed = ticket_embed(ticket, opener, panel, claimed_staff_name=claimed_staff_name)
    view = TicketActionsView(ticket)
    if disabled:
        for item in view.children:
            item.disabled = True  # type: ignore[attr-defined]
    with contextlib.suppress(discord.HTTPException):
        await message.edit(embed=embed, view=view)


async def _send_evaluation_dm(
    bot: LimerenceBot,
    guild: discord.Guild,
    ticket: Ticket,
    panel: TicketPanel | None,
    *,
    claimed_by_name: str,
    closed_by_name: str,
) -> None:
    """Envia a avaliacao por DM pro autor do ticket (metodo "dm"/"both" em
    EvaluationSettings). O fechamento em si ja aconteceu e ja foi commitado
    antes desta chamada — falha de DM (bloqueada, usuario saiu do servidor)
    nunca pode derrubar nem parecer que o fechamento falhou, so fica
    registrado em log."""
    opener = await _resolve_opener(bot, guild, ticket)
    if opener is None:
        logger.info(
            "Avaliação por DM não enviada — usuário do ticket %s não foi encontrado.", ticket.id
        )
        return
    eval_settings = await bot.config_service.get_evaluation_settings(guild.id)
    embed = evaluation_dm_embed(
        eval_settings,
        guild=guild,
        ticket=ticket,
        panel=panel,
        opener=opener,
        claimed_by_name=claimed_by_name,
        closed_by_name=closed_by_name,
    )
    try:
        await opener.send(embed=embed, view=DMEvaluationView(ticket.id))
    except discord.HTTPException:
        logger.info(
            "Não foi possível enviar a DM de avaliação do ticket %s (DM bloqueada ou "
            "usuário sem servidor em comum com o bot).",
            ticket.id,
        )


class TicketActionsView(SafeView):
    """Botoes Assumir/Liberar (um so, alterna conforme o estado) + Incluir/
    Remover/Fechar + Mais. Staff-only. Persistent (timeout=None), resolve o
    ticket pelo channel_id da interacao — nenhum dado sensivel no custom_id.

    `ticket` e opcional: soh define QUAL dos dois botoes (Assumir ou Liberar)
    aparece nesta instancia. Sem ele (registro persistente no boot, so pra
    dispatch depois de um restart) cai no padrao "Assumir". Os custom_ids de
    ambos sao os mesmos de sempre (`limerence:ticket:claim`/`:unclaim`) —
    trocar qual botao aparece nunca quebra o roteamento apos restart, porque o
    Discord so usa o custom_id gravado na propria mensagem pra decidir qual
    callback chamar."""

    def __init__(self, ticket: Ticket | None = None) -> None:
        super().__init__(timeout=None)
        claimed = ticket is not None and ticket.claimed_by_staff_id is not None
        if claimed:
            self.remove_item(self.claim)
        else:
            self.remove_item(self.unclaim)

    @discord.ui.button(
        label="Assumir",
        style=discord.ButtonStyle.success,
        custom_id="limerence:ticket:claim",
        emoji="🖐️",
        row=0,
    )
    async def claim(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if await _deny_if_cant(interaction, "claim"):
            return
        await interaction.response.defer(ephemeral=True)
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member) or interaction.channel_id is None:
            return

        # filtro extra por painel: se o painel que originou o ticket restringiu
        # os cargos que podem assumir, ele vale POR CIMA da permissao global de
        # `claim` (nunca no lugar dela). Ticket sem painel = nada muda.
        existing = await bot.ticket_service.get_by_channel_id(interaction.channel_id)
        panel = await bot.ticket_panel_service.get_panel_for_ticket(existing) if existing else None
        if not member_matches_panel_claim_roles(member, panel):
            await interaction.followup.send(
                "Apenas os cargos responsáveis por este painel podem assumir este ticket.",
                ephemeral=True,
            )
            return

        staff = await bot.staff_service.ensure_staff(guild.id, member.id, member.display_name)
        try:
            await bot.claim_service.claim_ticket(interaction.channel_id, staff.id)
        except ClaimError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        ticket = await bot.ticket_service.get_by_channel_id(interaction.channel_id)
        # background: log e so trilha/confirmacao aqui, nao precisa estar
        # gravado antes de responder ao usuario que clicou Assumir.
        bot.log_service.record_background(
            guild_id=guild.id,
            action=LogAction.CLAIM,
            actor_discord_id=member.id,
            staff_id=staff.id,
            ticket_id=ticket.id if ticket else None,
            category_snapshot=ticket.category.value if ticket else None,
            message=f"{member} assumiu o ticket.",
        )
        await bot.painel_service.refresh_dashboard(guild.id)
        if ticket is not None:
            # `panel` ja foi buscado acima (linha 144) pra checar claim_role_ids
            # — panel_id de um ticket nao muda depois de criado, entao reusar
            # aqui evita repetir a mesma consulta (get_panel_for_ticket) 2x
            # nesta mesma interacao.
            await _refresh_panel_message(
                interaction, ticket, claimed_staff_name=member.display_name, panel=panel
            )
        await interaction.followup.send(f"{member.mention} assumiu este ticket.", ephemeral=False)

    @discord.ui.button(
        label="Liberar",
        style=discord.ButtonStyle.secondary,
        custom_id="limerence:ticket:unclaim",
        emoji="🖐️",
        row=0,
    )
    async def unclaim(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if await _deny_if_cant(interaction, "unclaim"):
            return
        await interaction.response.defer(ephemeral=True)
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member) or interaction.channel_id is None:
            return

        staff = await bot.staff_service.ensure_staff(guild.id, member.id, member.display_name)
        try:
            await bot.claim_service.unclaim_ticket(interaction.channel_id, staff.id)
        except ClaimError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        ticket = await bot.ticket_service.get_by_channel_id(interaction.channel_id)
        bot.log_service.record_background(
            guild_id=guild.id,
            action=LogAction.UNCLAIM,
            actor_discord_id=member.id,
            staff_id=staff.id,
            ticket_id=ticket.id if ticket else None,
            category_snapshot=ticket.category.value if ticket else None,
            message=f"{member} liberou o ticket.",
        )
        await bot.painel_service.refresh_dashboard(guild.id)
        if ticket is not None:
            await _refresh_panel_message(interaction, ticket, claimed_staff_name=None)
        await interaction.followup.send(f"{member.mention} liberou este ticket.", ephemeral=False)

    @discord.ui.button(
        label="Incluir",
        style=discord.ButtonStyle.secondary,
        custom_id="limerence:ticket:include",
        emoji="➕",
        row=0,
    )
    async def include(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await member_is_staff(interaction):
            await interaction.response.send_message(
                "Apenas a staff pode usar esse botão.", ephemeral=True
            )
            return
        view = SafeView(timeout=120)
        view.add_item(_IncludeUserSelect())
        await interaction.response.send_message(
            "Selecione quem deseja incluir neste ticket:", view=view, ephemeral=True
        )

    @discord.ui.button(
        label="Remover",
        style=discord.ButtonStyle.secondary,
        custom_id="limerence:ticket:remove_member",
        emoji="➖",
        row=0,
    )
    async def remove(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await member_is_staff(interaction):
            await interaction.response.send_message(
                "Apenas a staff pode usar esse botão.", ephemeral=True
            )
            return
        view = SafeView(timeout=120)
        view.add_item(_RemoveUserSelect())
        await interaction.response.send_message(
            "Selecione quem deseja remover deste ticket:", view=view, ephemeral=True
        )

    @discord.ui.button(
        label="Fechar",
        style=discord.ButtonStyle.danger,
        custom_id="limerence:ticket:close",
        emoji="🔒",
        row=0,
    )
    async def close(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        # Deferir de imediato: sem ramo de modal, e a checagem de permissao +
        # get_by_channel_id ja rodam antes de qualquer resposta.
        await interaction.response.defer()
        if await _deny_if_cant(interaction, "fechar", already_deferred=True):
            return
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member) or interaction.channel_id is None:
            return

        existing_ticket = await bot.ticket_service.get_by_channel_id(interaction.channel_id)
        if existing_ticket is None:
            await interaction.followup.send("Ticket não encontrado.", ephemeral=True)
            return
        if existing_ticket.claimed_by_staff_id is None:
            await interaction.followup.send(
                "Este ticket ainda não foi assumido por ninguém. Clique em **Assumir** antes de fechar.",
                ephemeral=True,
            )
            return

        confirm_view = ConfirmCloseView(member.id)
        await interaction.followup.send(
            "Tem certeza que deseja fechar este ticket?", view=confirm_view, ephemeral=True
        )
        await confirm_view.wait()
        if not confirm_view.confirmed:
            return

        claimed_staff = (
            await bot.staff_service.get_by_id(existing_ticket.claimed_by_staff_id)
            if existing_ticket.claimed_by_staff_id is not None
            else None
        )
        # buscado uma unica vez aqui e reaproveitado abaixo (reedicao do
        # painel + embed da DM de avaliacao) — panel_id nao muda depois que o
        # ticket e criado, entao nao ha necessidade de buscar de novo.
        panel = await bot.ticket_panel_service.get_panel_for_ticket(existing_ticket)
        try:
            result = await bot.ticket_service.close_ticket(interaction.channel_id, member.id)
        except (TicketNotFoundError, TicketNotClaimedError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        ticket = result.ticket
        claimed_staff_name = claimed_staff.display_name if claimed_staff else None

        await _refresh_panel_message(
            interaction,
            ticket,
            claimed_staff_name=claimed_staff_name,
            disabled=True,
            panel=panel,
        )

        bot.log_service.record_background(
            guild_id=guild.id,
            action=LogAction.FECHAMENTO,
            actor_discord_id=member.id,
            ticket_id=ticket.id,
            category_snapshot=ticket.category.value,
            message=f"{member} fechou o ticket.",
        )
        await bot.painel_service.refresh_dashboard(guild.id)

        if ticket.voice_channel_id is not None:
            voice_channel = guild.get_channel(ticket.voice_channel_id)
            if isinstance(voice_channel, discord.VoiceChannel):
                try:
                    await voice_channel.delete(reason="Ticket fechado.")
                except discord.HTTPException:
                    pass

        channel = interaction.channel
        if ticket.status == TicketStatus.CLOSED and isinstance(channel, discord.TextChannel):
            await channel.send(
                embed=ticket_closed_summary_embed(
                    guild=guild,
                    ticket=ticket,
                    panel=panel,
                    closed_by_mention=member.mention,
                    closed_by_name=member.display_name,
                    claimed_by_name=claimed_staff_name or "Não assumido",
                ),
                view=TicketClosedView(),
            )
            if ticket.claimed_by_staff_id is not None:
                await announce_achievements(
                    bot, channel, ticket.claimed_by_staff_id, result.unlocked_achievements
                )
            opener = guild.get_member(ticket.opened_by_discord_id)
            eval_settings = await bot.config_service.get_evaluation_settings(guild.id)
            behaviour = await bot.ticket_panel_service.behaviour_for_ticket(ticket, guild.id)
            if eval_settings.enabled and behaviour.evaluation_enabled:
                method = normalize_evaluation_method(eval_settings.evaluation_method)
                # "ticket"/"both": mantem exatamente o comportamento historico
                # (mensagem separada com os 5 botoes de estrela no canal).
                if opener is not None and method in ("ticket", "both"):
                    await channel.send(
                        content=opener.mention,
                        embed=discord.Embed(
                            title="Como foi o seu atendimento?",
                            description="Avalie o suporte que você recebeu.",
                        ),
                        view=EvaluationView(),
                    )
                # "dm"/"both": avaliacao tambem (ou so) por DM — falha de DM
                # (bloqueada, etc.) nunca afeta o fechamento, que ja aconteceu.
                if method in ("dm", "both"):
                    await _send_evaluation_dm(
                        bot,
                        guild,
                        ticket,
                        panel,
                        claimed_by_name=claimed_staff_name or "Não assumido",
                        closed_by_name=member.display_name,
                    )

    @discord.ui.button(
        label="Mais",
        style=discord.ButtonStyle.secondary,
        custom_id="limerence:ticket:more",
        emoji="⚙️",
        row=1,
    )
    async def more(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await member_is_staff(interaction):
            await interaction.response.send_message(
                "Apenas a staff pode usar esse botão.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "⚙️ Mais opções:", view=_MoreOptionsView(), ephemeral=True
        )


class _IncludeUserSelect(discord.ui.UserSelect[Any]):
    """Concede acesso ao canal do ticket pro usuario escolhido. Reaproveita as
    mesmas permissoes usadas na criacao do ticket (ver `TicketService.create_ticket`):
    ver canal + mandar mensagem + ler historico."""

    def __init__(self) -> None:
        super().__init__(placeholder="Selecione um usuário...", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        guild = interaction.guild
        channel = interaction.channel
        if (
            guild is None
            or not isinstance(channel, discord.TextChannel)
            or interaction.channel_id is None
        ):
            return
        target = self.values[0]
        if not isinstance(target, discord.Member):
            await interaction.response.send_message("Usuário inválido.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        ticket = await bot.ticket_service.get_by_channel_id(interaction.channel_id)
        if ticket is None:
            await interaction.followup.send("Ticket não encontrado.", ephemeral=True)
            return

        try:
            await channel.set_permissions(
                target,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                reason=f"Incluído no ticket por {interaction.user}",
            )
        except discord.HTTPException:
            await interaction.followup.send(
                "Não foi possível conceder acesso a esse usuário.", ephemeral=True
            )
            return

        # background: acesso ja foi concedido (set_permissions acima); a
        # auditoria e so trilha, mesmo padrao ja aplicado em claim/unclaim/fechar.
        bot.audit_log_service.record_background(
            guild_id=guild.id,
            category=AuditLogCategory.TICKETS,
            action="Usuário incluído no ticket",
            executor_id=interaction.user.id,
            executor_name=str(interaction.user),
            target_id=target.id,
            target_name=str(target),
            details={"ticket_id": str(ticket.id), "canal": channel.name},
        )
        await channel.send(
            f"➕ {target.mention} foi incluído neste ticket por {interaction.user.mention}."
        )
        await interaction.followup.send(
            f"{target.mention} agora tem acesso a este ticket.", ephemeral=True
        )


class _RemoveUserSelect(discord.ui.UserSelect[Any]):
    """Remove o acesso ao canal do usuario escolhido. Nunca remove quem abriu
    o ticket (sem regra explicita do sistema pra isso) nem administradores —
    protecao minima contra abuso do botao."""

    def __init__(self) -> None:
        super().__init__(placeholder="Selecione um usuário...", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        guild = interaction.guild
        channel = interaction.channel
        if (
            guild is None
            or not isinstance(channel, discord.TextChannel)
            or interaction.channel_id is None
        ):
            return
        target = self.values[0]
        if not isinstance(target, discord.Member):
            await interaction.response.send_message("Usuário inválido.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        ticket = await bot.ticket_service.get_by_channel_id(interaction.channel_id)
        if ticket is None:
            await interaction.followup.send("Ticket não encontrado.", ephemeral=True)
            return

        if target.id == ticket.opened_by_discord_id:
            await interaction.followup.send(
                "Não é possível remover quem abriu o ticket por este botão.", ephemeral=True
            )
            return
        if target.guild_permissions.administrator:
            await interaction.followup.send(
                "Não é possível remover um administrador do ticket.", ephemeral=True
            )
            return

        overwrite = channel.overwrites_for(target)
        if overwrite.is_empty():
            await interaction.followup.send(
                "Esse usuário não tem acesso individual a este ticket.", ephemeral=True
            )
            return

        try:
            await channel.set_permissions(
                target, overwrite=None, reason=f"Removido do ticket por {interaction.user}"
            )
        except discord.HTTPException:
            await interaction.followup.send(
                "Não foi possível remover o acesso desse usuário.", ephemeral=True
            )
            return

        # background: acesso ja foi revogado (set_permissions acima); a
        # auditoria e so trilha, mesmo padrao ja aplicado em claim/unclaim/fechar.
        bot.audit_log_service.record_background(
            guild_id=guild.id,
            category=AuditLogCategory.TICKETS,
            action="Usuário removido do ticket",
            executor_id=interaction.user.id,
            executor_name=str(interaction.user),
            target_id=target.id,
            target_name=str(target),
            details={"ticket_id": str(ticket.id), "canal": channel.name},
        )
        await channel.send(
            f"➖ {target.mention} foi removido deste ticket por {interaction.user.mention}."
        )
        await interaction.followup.send(f"Acesso de {target.mention} removido.", ephemeral=True)


async def _create_voice_channel_for_ticket(interaction: discord.Interaction) -> None:
    """Cria o canal de voz vinculado ao ticket atual. Extraido do antigo botao
    independente 'Criar Canal de Voz' — mesma logica, agora vivendo dentro do
    menu ⚙️ Mais (nao duplica, so muda de onde e chamado)."""
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    guild = interaction.guild
    member = interaction.user
    channel = interaction.channel
    if (
        guild is None
        or not isinstance(member, discord.Member)
        or interaction.channel_id is None
        or not isinstance(channel, discord.TextChannel)
    ):
        return

    ticket = await bot.ticket_service.get_by_channel_id(interaction.channel_id)
    if ticket is None:
        await interaction.followup.send("Ticket não encontrado.", ephemeral=True)
        return

    if ticket.voice_channel_id is not None:
        existing = guild.get_channel(ticket.voice_channel_id)
        if isinstance(existing, discord.VoiceChannel):
            await interaction.followup.send(
                f"Já existe um canal de voz para este ticket: {existing.mention}",
                ephemeral=True,
            )
            return

    settings = await bot.config_service.get_settings(guild.id)
    staff_role_ids = [
        role_id
        for role_id in (settings.moderator_role_id, settings.dev_role_id, settings.ceo_role_id)
        if role_id is not None
    ]

    opener = guild.get_member(ticket.opened_by_discord_id)
    overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
    }
    if opener is not None:
        overwrites[opener] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
    for role_id in staff_role_ids:
        role = guild.get_role(role_id)
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)

    try:
        voice_channel = await guild.create_voice_channel(
            name=f"voz-{channel.name}"[:90],
            category=channel.category,
            overwrites=overwrites,
            reason=f"Canal de voz do ticket criado por {member}",
        )
    except discord.HTTPException:
        await interaction.followup.send(
            "Não foi possível criar o canal de voz. Tente novamente mais tarde.",
            ephemeral=True,
        )
        return

    await bot.ticket_service.set_voice_channel(interaction.channel_id, voice_channel.id)
    await interaction.followup.send(f"Canal de voz criado: {voice_channel.mention}", ephemeral=True)


async def _send_ticket_info(interaction: discord.Interaction) -> None:
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    if interaction.channel_id is None:
        return
    ticket = await bot.ticket_service.get_by_channel_id(interaction.channel_id)
    if ticket is None:
        await interaction.followup.send("Ticket não encontrado.", ephemeral=True)
        return
    panel = await bot.ticket_panel_service.get_panel_for_ticket(ticket)
    claimed_staff = (
        await bot.staff_service.get_by_id(ticket.claimed_by_staff_id)
        if ticket.claimed_by_staff_id is not None
        else None
    )
    embed = discord.Embed(title="📋 Informações do ticket", color=EMBED_COLOR_DEFAULT)
    embed.add_field(name="ID", value=f"`{str(ticket.id)[:8]}`", inline=True)
    embed.add_field(name="Categoria", value=panel.name if panel else ticket.category.value, inline=True)
    embed.add_field(name="Status", value=ticket_panel_status_label(ticket), inline=True)
    embed.add_field(name="Aberto por", value=f"<@{ticket.opened_by_discord_id}>", inline=True)
    embed.add_field(
        name="Assumido por",
        value=claimed_staff.display_name if claimed_staff else "Não assumido",
        inline=True,
    )
    embed.add_field(
        name="Aberto", value=discord.utils.format_dt(ticket.created_at, style="R"), inline=True
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


class _MoreOptionsView(SafeView):
    """Sub-menu do botao ⚙️ Mais — funcionalidades secundarias que nao
    precisam de destaque na linha principal. So funcoes que ja existem no
    projeto: criar canal de voz (antigo botao independente, migrado pra ca) e
    gerar transcricao (mesma funcao usada em `TicketClosedView`)."""

    def __init__(self) -> None:
        super().__init__(timeout=180)

    @discord.ui.button(label="Criar canal de voz", emoji="🔊", style=discord.ButtonStyle.secondary)
    async def voice(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await _create_voice_channel_for_ticket(interaction)

    @discord.ui.button(label="Ver informações", emoji="📋", style=discord.ButtonStyle.secondary)
    async def info(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await _send_ticket_info(interaction)

    @discord.ui.button(label="Gerar transcrição", emoji="📝", style=discord.ButtonStyle.secondary)
    async def transcript(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await member_is_staff(interaction):
            await interaction.followup.send(
                "Apenas a staff pode usar esse botão.", ephemeral=True
            )
            return
        await send_ticket_transcript(interaction)
