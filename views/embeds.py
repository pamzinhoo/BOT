from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from database.models.audit_log import AuditLogCategory
from database.models.automod import AutoModLog, AutoModSettings
from database.models.command_help import CommandHelp
from database.models.log import LogAction
from database.models.payment import PaymentHistory
from database.models.payment_dm_settings import PaymentDmSettings
from database.models.plan import Plan
from database.models.poll import Poll, PollOption
from database.models.punishment import APPEALABLE_TYPES, Punishment, PunishmentType
from database.models.punishment_appeal import PunishmentAppeal
from database.models.staff_stats import StaffStats
from database.models.ticket import Ticket, TicketCategory
from database.models.ticket_panel import TicketPanel
from services.automod_service import EffectiveWord
from services.plan_service import render_placeholders
from services.ranking_service import RankingEntry
from services.staff_service import StaffProfile
from utils.constants import (
    APPEAL_STATUS_LABELS,
    AUDIT_CATEGORY_COLORS,
    AUDIT_CATEGORY_LABELS,
    AUDIT_CATEGORY_TARGET_KIND,
    CATEGORY_CONFIRM_TEXT,
    CATEGORY_LABELS,
    EMBED_COLOR_DANGER,
    EMBED_COLOR_DARK,
    EMBED_COLOR_DEFAULT,
    EMBED_COLOR_ORANGE,
    EMBED_COLOR_PURPLE,
    EMBED_COLOR_SUCCESS,
    EMBED_COLOR_VIOLET,
    EMBED_COLOR_WARNING,
    HELP_CATEGORY_LABELS,
    LOG_ACTION_LABELS,
    PUNISHMENT_STATUS_LABELS,
    PUNISHMENT_TYPE_LABELS,
    achievement_label,
)
from utils.formatter import rank_marker
from utils.time import humanize_duration

if TYPE_CHECKING:
    from services.punishment_review_service import PendingPunishmentItem


def ticket_embed(ticket: Ticket, opener: discord.Member | discord.User) -> discord.Embed:
    embed = discord.Embed(
        title=f"{CATEGORY_LABELS[ticket.category]}",
        description=f"Ticket aberto por {opener.mention}. Aguarde, a staff ja foi notificada.",
        color=EMBED_COLOR_DEFAULT,
    )
    embed.set_footer(text=f"Categoria: {ticket.category.value}")
    return embed


def staff_profile_embed(profile: StaffProfile, member: discord.Member | discord.User) -> discord.Embed:
    stats: StaffStats = profile.stats
    embed = discord.Embed(title=f"📋 Perfil de {profile.staff.display_name}", color=EMBED_COLOR_DEFAULT)
    embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(name="🎫 Tickets fechados", value=str(stats.tickets_fechados), inline=True)
    embed.add_field(
        name="⏱️ Tempo médio", value=humanize_duration(stats.tempo_medio_fechamento_s), inline=True
    )
    embed.add_field(
        name="⚡ Primeira resposta",
        value=humanize_duration(stats.tempo_medio_primeira_resposta_s),
        inline=True,
    )
    embed.add_field(
        name="⭐ Avaliação",
        value=f"{float(stats.avaliacao_media):.2f}★ ({stats.avaliacoes_count})",
        inline=True,
    )
    embed.add_field(name="🔥 Sequência atual", value=f"{stats.current_streak_days} dias", inline=True)
    embed.add_field(name="🏔️ Maior sequência", value=f"{stats.best_streak_days} dias", inline=True)
    embed.add_field(name="📆 Dias ativos", value=str(stats.total_active_days), inline=True)
    embed.add_field(name="📈 Recorde diário", value=f"{stats.best_day_ticket_count} tickets", inline=True)
    embed.add_field(name="💯 Perfect Streak", value=f"{stats.current_perfect_streak} ★5 seguidas", inline=True)
    embed.add_field(name="📅 Desde", value=str(profile.staff.created_at.year), inline=True)
    embed.add_field(
        name="🎯 Especialidade",
        value=CATEGORY_LABELS[profile.specialty] if profile.specialty else "—",
        inline=True,
    )

    if profile.achievements:
        counts: dict[str, int] = {}
        for achievement in profile.achievements:
            key = "monthly_top1" if achievement.key.startswith("monthly_top1_") else achievement.key
            label = "🏆 1º lugar do mês" if key == "monthly_top1" else achievement_label(achievement.key)
            counts[label] = counts.get(label, 0) + 1
        lines = [
            f"{label} (x{count})" if count > 1 else label for label, count in counts.items()
        ]
        embed.add_field(name="Conquistas", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Conquistas", value="Nenhuma ainda — bora trabalhar! 💪", inline=False)

    if profile.recent_tickets:
        lines = []
        for ticket in profile.recent_tickets:
            closed = (
                discord.utils.format_dt(ticket.closed_at, style="R") if ticket.closed_at else "em atendimento"
            )
            lines.append(f"#{str(ticket.id)[:8]} - {CATEGORY_LABELS[ticket.category]} ({closed})")
        embed.add_field(name="Últimos Tickets", value="\n".join(lines), inline=False)

    return embed


def ranking_embed(entries: list[RankingEntry], period_label: str) -> discord.Embed:
    embed = discord.Embed(title=f"🏆 Ranking — {period_label}", color=EMBED_COLOR_DEFAULT)
    if not entries:
        embed.description = "Sem dados suficientes ainda."
        return embed
    lines = [
        f"{rank_marker(i)} {entry.staff.display_name} — {entry.tickets} tickets, ⭐ {entry.avaliacao_media:.1f}"
        for i, entry in enumerate(entries[:10])
    ]
    embed.description = "\n".join(lines)
    return embed


def painel_embed(open_tickets_count: int, top5: list[RankingEntry]) -> discord.Embed:
    embed = discord.Embed(title="📊 Painel da Staff", color=EMBED_COLOR_DEFAULT)
    embed.add_field(name="🎫 Tickets Abertos", value=str(open_tickets_count), inline=True)
    lines = [
        f"{rank_marker(i)} {entry.staff.display_name} — {entry.tickets}"
        for i, entry in enumerate(top5)
    ]
    embed.add_field(name="🏆 TOP 5", value="\n".join(lines) or "Sem dados ainda.", inline=False)
    return embed


def log_embed(action: LogAction, message: str) -> discord.Embed:
    return discord.Embed(title=LOG_ACTION_LABELS[action], description=message, color=EMBED_COLOR_DEFAULT)


def _format_target(category: AuditLogCategory, target_id: int | None, target_name: str | None) -> str:
    kind = AUDIT_CATEGORY_TARGET_KIND.get(category, "user")
    if target_id is None:
        return target_name or "—"
    if kind == "channel":
        return f"<#{target_id}>"
    if kind == "role":
        return f"<@&{target_id}>"
    if kind == "none":
        return target_name or str(target_id)
    return f"<@{target_id}>"


def audit_log_embed(
    category: AuditLogCategory,
    action: str,
    *,
    executor_name: str | None,
    executor_id: int | None,
    target_name: str | None,
    target_id: int | None,
    reason: str | None,
    details: dict[str, object],
    config_category: str | None = None,
    config_name: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=AUDIT_CATEGORY_LABELS[category],
        description=action,
        color=AUDIT_CATEGORY_COLORS[category],
    )
    executor_value = f"<@{executor_id}>" if executor_id is not None else (executor_name or "Desconhecido")
    embed.add_field(name="Executor", value=executor_value, inline=True)
    if target_id is not None or target_name is not None:
        target_value = _format_target(category, target_id, target_name)
        embed.add_field(name="Alvo", value=target_value, inline=True)
    if config_name is not None:
        field_label = f"{config_category} — {config_name}" if config_category else config_name
        embed.add_field(name="Configuração", value=field_label, inline=False)
        embed.add_field(name="Antes", value=old_value or "—", inline=True)
        embed.add_field(name="Depois", value=new_value or "—", inline=True)
    embed.add_field(name="Motivo", value=reason or "—", inline=False)
    if details:
        details_text = "\n".join(f"**{key}:** {value}" for key, value in details.items())
        embed.add_field(name="Detalhes", value=details_text[:1024], inline=False)
    embed.timestamp = discord.utils.utcnow()
    embed.set_footer(text="Audit Log • Limerence")
    return embed


def category_confirm_embed(category: TicketCategory) -> discord.Embed:
    return discord.Embed(description=CATEGORY_CONFIRM_TEXT[category], color=EMBED_COLOR_DEFAULT)


def open_ticket_panel_embed(panel: TicketPanel | None = None) -> discord.Embed:
    """Embed do painel de abertura de tickets.

    Sem `panel` (fluxo legado /painel-setup + PainelView) devolve exatamente a
    embed fixa de sempre — os visuais do painel legado nao mudam. Com `panel`,
    monta tudo a partir da configuracao do painel (titulo/descricao/cor/imagem/
    thumbnail/rodape), caindo nos mesmos padroes quando o campo esta vazio."""
    if panel is None:
        return discord.Embed(
            title="🎫 Suporte",
            description=(
                "Selecione uma categoria abaixo para abrir um ticket com a nossa equipe de suporte."
            ),
            color=EMBED_COLOR_DEFAULT,
        )

    embed = discord.Embed(
        title=panel.embed_title or panel.name,
        description=(
            panel.embed_description
            or "Clique no botão abaixo para abrir um ticket com a nossa equipe."
        ),
        color=discord.Color(panel.embed_color) if panel.embed_color is not None else EMBED_COLOR_DEFAULT,
    )
    if panel.embed_image_url:
        embed.set_image(url=panel.embed_image_url)
    if panel.embed_thumbnail_url:
        embed.set_thumbnail(url=panel.embed_thumbnail_url)
    if panel.embed_footer:
        embed.set_footer(text=panel.embed_footer)
    return embed


PAYMENT_DM_DEFAULTS = {
    True: {
        "title": "🎉 Seu pagamento foi aprovado!",
        "description": (
            "Olá, **{user}**!\n\n"
            "Recebemos e confirmamos o pagamento do seu pedido.\n\n"
            "Seu plano **{plan}** já foi ativado e todos os benefícios já estão disponíveis para você.\n\n"
            "Muito obrigado por apoiar nosso projeto. Sua contribuição ajuda diretamente no "
            "desenvolvimento da comunidade e de novas funcionalidades.\n\n"
            "Esperamos que aproveite todos os benefícios!\n\n"
            "❤️ Equipe {guild}"
        ),
    },
    False: {
        "title": "⚠️ Seu pagamento não pôde ser confirmado",
        "description": (
            "Olá, **{user}**!\n\n"
            "No momento não foi possível localizar ou validar o pagamento referente ao seu pedido.\n\n"
            "Isso pode acontecer por diversos motivos, como:\n\n"
            "• pagamento ainda não compensado;\n"
            "• valor incorreto;\n"
            "• divergência nas informações enviadas.\n\n"
            "Caso acredite que houve algum engano, abra um ticket ou entre em contato com nossa "
            "equipe para que possamos verificar.\n\n"
            "Obrigado pela compreensão.\n\n"
            "❤️ Equipe {guild}"
        ),
    },
}


def payment_dm_embed(
    settings: PaymentDmSettings | None,
    *,
    approved: bool,
    member: discord.Member,
    plan: Plan,
    payment: PaymentHistory,
    staff: discord.Member | discord.User | None = None,
) -> discord.Embed:
    """Embed enviado por DM ao comprador quando um staff aprova/rejeita um
    pagamento. Sem `settings` (ou com campo vazio), cai no texto padrao —
    igual ao padrao de `open_ticket_panel_embed`."""
    defaults = PAYMENT_DM_DEFAULTS[approved]
    prefix = "approved" if approved else "rejected"

    def _field(name: str) -> str | None:
        return getattr(settings, f"{prefix}_embed_{name}") if settings is not None else None

    title = render_placeholders(
        _field("title") or defaults["title"], member=member, guild=member.guild, plan=plan,
        payment_id=payment.id, staff=staff,
    )
    description = render_placeholders(
        _field("description") or defaults["description"], member=member, guild=member.guild, plan=plan,
        payment_id=payment.id, staff=staff,
    )
    color_value = _field("color")
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color(color_value) if color_value is not None else (
            EMBED_COLOR_SUCCESS if approved else EMBED_COLOR_DANGER
        ),
    )
    footer = _field("footer")
    if footer:
        embed.set_footer(text=render_placeholders(
            footer, member=member, guild=member.guild, plan=plan, payment_id=payment.id, staff=staff,
        ))
    thumbnail = _field("thumbnail_url")
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    image = _field("image_url")
    if image:
        embed.set_image(url=image)
    return embed


def ticket_form_answers_embed(answers: list[tuple[str, str]]) -> discord.Embed:
    """Respostas do formulario do painel, postadas no canal do ticket."""
    embed = discord.Embed(title="📝 Respostas do formulário", color=EMBED_COLOR_DEFAULT)
    for label, answer in answers:
        embed.add_field(name=label[:256], value=(answer or "—")[:1024], inline=False)
    return embed


def ticket_approval_request_embed(panel: TicketPanel) -> discord.Embed:
    """Pedido de aprovacao mostrado junto com os botoes Aprovar/Reprovar."""
    role_line = (
        f"\nCargo entregue na aprovação: <@&{panel.approval_granted_role_id}>"
        if panel.approval_granted_role_id is not None
        else ""
    )
    return discord.Embed(
        title="🧾 Aguardando análise",
        description=(
            f"Este ticket veio do painel **{panel.name}** e precisa de uma decisão da equipe."
            f"{role_line}"
        ),
        color=EMBED_COLOR_WARNING,
    )


def category_select_options() -> list[discord.SelectOption]:
    return [
        discord.SelectOption(label=label, value=category.value)
        for category, label in CATEGORY_LABELS.items()
    ]


def category_from_value(value: str) -> TicketCategory:
    return TicketCategory(value)


def punishment_confirm_embed(
    *,
    user: discord.Member | discord.User,
    ptype: PunishmentType,
    duration_label: str | None,
    reason: str,
    proofs: list[str],
    staff_name: str,
    is_review: bool = False,
) -> discord.Embed:
    """Etapa 2 do fluxo de dupla confirmação: revisão antes de qualquer validação."""
    embed = discord.Embed(title="⚠️ REVISÃO DE PUNIÇÃO", color=EMBED_COLOR_WARNING)
    embed.add_field(name="Usuário", value=f"{user}", inline=True)
    embed.add_field(name="ID", value=str(user.id), inline=True)
    embed.add_field(name="Tipo", value=PUNISHMENT_TYPE_LABELS[ptype], inline=False)
    embed.add_field(name="Duração", value=duration_label or "Permanente", inline=True)
    embed.add_field(name="Motivo", value=reason, inline=False)
    embed.add_field(name="Provas", value="\n".join(proofs) or "—", inline=False)
    embed.add_field(name="Staff responsável", value=staff_name, inline=False)
    if is_review:
        embed.add_field(
            name="Ação",
            value="Usuário será colocado em análise (isolado) antes do banimento definitivo.",
            inline=False,
        )
    return embed


def punishment_dm_notified_embed() -> discord.Embed:
    """Mostrado pra staff quando a DM de aviso (Etapa 4) foi enviada com sucesso."""
    embed = discord.Embed(
        title="✅ Usuário notificado",
        description=(
            "A mensagem de punição foi enviada com sucesso.\n\nDeseja aplicar a punição?"
        ),
        color=EMBED_COLOR_SUCCESS,
    )
    return embed


def punishment_dm_failed_embed(reason: str) -> discord.Embed:
    """Mostrado pra staff quando a DM de aviso (Etapa 4) falhou."""
    embed = discord.Embed(
        title="⚠️ Não foi possível enviar DM",
        description=(
            "Possíveis motivos:\n"
            "- usuário bloqueou mensagens privadas\n"
            "- Discord recusou a mensagem\n\n"
            f"**Erro registrado:** {reason}\n\n"
            "Deseja continuar mesmo assim?"
        ),
        color=EMBED_COLOR_WARNING,
    )
    return embed


def punishment_log_embed(punishment: Punishment) -> discord.Embed:
    embed = discord.Embed(title="🔨 NOVA PUNIÇÃO", color=EMBED_COLOR_DANGER)
    embed.add_field(name="👮 Staff responsável", value=f"<@{punishment.staff_id}>", inline=True)
    embed.add_field(name="ID Staff", value=str(punishment.staff_id), inline=True)
    embed.add_field(name="👤 Usuário punido", value=f"<@{punishment.user_id}>", inline=True)
    embed.add_field(name="ID", value=str(punishment.user_id), inline=True)
    embed.add_field(name="⚠️ Tipo", value=PUNISHMENT_TYPE_LABELS[punishment.type], inline=False)
    if punishment.duration_seconds:
        embed.add_field(
            name="⏳ Duração", value=humanize_duration(punishment.duration_seconds), inline=True
        )
    embed.add_field(name="📄 Motivo", value=punishment.reason, inline=False)
    embed.add_field(name="📎 Provas", value="\n".join(punishment.proofs) or "—", inline=False)
    if punishment.dm_sent:
        embed.add_field(name="DM enviada", value="✅ Sim", inline=True)
    else:
        embed.add_field(
            name="DM enviada",
            value=f"❌ Não\n**Motivo:** {punishment.dm_failure_reason or '—'}",
            inline=True,
        )
    embed.add_field(name="🆔 ID da punição", value=punishment.punishment_code, inline=False)
    embed.timestamp = punishment.created_at
    return embed


def punishment_dm_embed(punishment: Punishment) -> discord.Embed:
    """Etapa 4: aviso de punição enviado ANTES da punição ser de fato aplicada."""
    embed = discord.Embed(title="🔨 Aviso de punição", color=EMBED_COLOR_DANGER)
    embed.description = "Você receberá uma punição no servidor Limerence."
    embed.add_field(name="Tipo", value=PUNISHMENT_TYPE_LABELS[punishment.type], inline=False)
    if punishment.duration_seconds:
        embed.add_field(
            name="Duração", value=humanize_duration(punishment.duration_seconds), inline=False
        )
    embed.add_field(name="Motivo", value=punishment.reason, inline=False)
    embed.add_field(
        name="Aplicado por", value=punishment.staff_name or str(punishment.staff_id), inline=False
    )
    embed.add_field(name="Provas", value="\n".join(punishment.proofs) or "—", inline=False)
    embed.add_field(name="ID da punição", value=punishment.punishment_code, inline=False)
    embed.timestamp = punishment.created_at
    if punishment.type in APPEALABLE_TYPES:
        embed.add_field(
            name="Caso queira contestar essa decisão",
            value=(
                "Use o botão abaixo para enviar um recurso.\n"
                "Caso o botão não funcione, envie aqui nessa DM:\n"
                f"`!recorrer {punishment.punishment_code} Seu motivo aqui`"
            ),
            inline=False,
        )
    return embed


def punishment_review_dm_embed(punishment: Punishment) -> discord.Embed:
    """Etapa 22: aviso enviado quando a punição entra em análise (isolamento), em vez
    de aplicada de imediato — usuário ainda está no servidor, com contexto normal."""
    embed = discord.Embed(title="⚠️ Aviso de punição em análise", color=EMBED_COLOR_WARNING)
    embed.description = "Você recebeu uma punição no servidor Limerence."
    embed.add_field(name="Tipo", value=PUNISHMENT_TYPE_LABELS[punishment.type], inline=True)
    embed.add_field(name="Status", value="Em análise", inline=True)
    embed.add_field(name="Motivo", value=punishment.reason, inline=False)
    embed.add_field(
        name="Aplicado por", value=punishment.staff_name or str(punishment.staff_id), inline=False
    )
    embed.add_field(name="Código", value=punishment.punishment_code, inline=False)
    embed.timestamp = punishment.created_at
    embed.add_field(
        name="Você pode enviar um recurso antes da decisão final",
        value=(
            "Use o botão abaixo.\n"
            "Caso o botão não funcione, envie aqui nessa DM:\n"
            f"`!recorrer {punishment.punishment_code} Seu motivo aqui`"
        ),
        inline=False,
    )
    return embed


def punishment_status_embed(punishment: Punishment, *, time_remaining: str | None) -> discord.Embed:
    """Usado por /punicao_ver."""
    embed = discord.Embed(title=f"🔎 Punição {punishment.punishment_code}", color=EMBED_COLOR_DEFAULT)
    embed.add_field(name="Usuário", value=f"<@{punishment.user_id}>", inline=True)
    embed.add_field(name="ID", value=str(punishment.user_id), inline=True)
    embed.add_field(name="Tipo", value=PUNISHMENT_TYPE_LABELS[punishment.type], inline=False)
    embed.add_field(name="Status", value=PUNISHMENT_STATUS_LABELS[punishment.status], inline=False)
    if time_remaining is not None:
        embed.add_field(name="Tempo restante para recorrer", value=time_remaining, inline=False)
    embed.add_field(name="Motivo", value=punishment.reason, inline=False)
    embed.timestamp = punishment.created_at
    return embed


def appeal_review_embed(punishment: Punishment, appeal: PunishmentAppeal) -> discord.Embed:
    embed = discord.Embed(title="📨 NOVO RECURSO DE PUNIÇÃO", color=EMBED_COLOR_DEFAULT)
    embed.add_field(name="Usuário", value=f"<@{appeal.user_id}>", inline=True)
    embed.add_field(name="ID", value=str(appeal.user_id), inline=True)
    embed.add_field(name="Punição", value=punishment.punishment_code, inline=False)
    embed.add_field(name="Tipo", value=PUNISHMENT_TYPE_LABELS[punishment.type], inline=True)
    embed.add_field(
        name="Aplicado por", value=punishment.staff_name or str(punishment.staff_id), inline=True
    )
    embed.add_field(name="Motivo original", value=punishment.reason, inline=False)
    embed.add_field(name="📝 Motivo do recurso", value=appeal.message, inline=False)
    if appeal.additional_info:
        embed.add_field(name="Informações adicionais", value=appeal.additional_info, inline=False)
    embed.add_field(name="Status", value=APPEAL_STATUS_LABELS[appeal.status], inline=False)
    embed.timestamp = appeal.created_at
    return embed


def appeal_accepted_dm_embed(punishment: Punishment, reviewer_name: str) -> discord.Embed:
    embed = discord.Embed(
        title="✅ Seu recurso foi aceito!",
        description="Sua punição foi removida.",
        color=EMBED_COLOR_SUCCESS,
    )
    embed.add_field(name="Sua punição", value=punishment.punishment_code, inline=False)
    embed.add_field(name="Responsável", value=reviewer_name, inline=False)
    return embed


def appeal_denied_dm_embed(reason: str, reviewer_name: str) -> discord.Embed:
    embed = discord.Embed(
        title="❌ Seu recurso foi negado.",
        description="Sua punição continuará ativa.",
        color=EMBED_COLOR_DANGER,
    )
    embed.add_field(name="Motivo", value=reason, inline=False)
    embed.add_field(name="Responsável", value=reviewer_name, inline=False)
    return embed


def punishment_revoked_log_embed(punishment: Punishment, *, via_appeal: bool) -> discord.Embed:
    embed = discord.Embed(
        title="🔓 PUNIÇÃO REMOVIDA POR RECURSO" if via_appeal else "🔓 PUNIÇÃO REVOGADA",
        color=EMBED_COLOR_SUCCESS,
    )
    embed.add_field(name="Usuário", value=f"<@{punishment.user_id}>", inline=True)
    embed.add_field(name="Punição", value=punishment.punishment_code, inline=True)
    embed.add_field(
        name="Aceito por" if via_appeal else "Revogada por",
        value=punishment.revoked_by_name or str(punishment.revoked_by_id),
        inline=False,
    )
    if punishment.revoke_reason:
        embed.add_field(name="Motivo", value=punishment.revoke_reason, inline=False)
    embed.timestamp = discord.utils.utcnow()
    return embed


def punishment_history_embed(
    user: discord.Member | discord.User, punishments: list[Punishment]
) -> discord.Embed:
    embed = discord.Embed(title=f"Histórico de {user}", color=EMBED_COLOR_DEFAULT)
    counts: dict[PunishmentType, int] = {}
    for entry in punishments:
        counts[entry.type] = counts.get(entry.type, 0) + 1

    embed.add_field(name="Advertências", value=str(counts.get(PunishmentType.ADVERTENCIA, 0)), inline=True)
    embed.add_field(name="Timeouts", value=str(counts.get(PunishmentType.TIMEOUT, 0)), inline=True)
    bans = counts.get(PunishmentType.BAN, 0) + counts.get(PunishmentType.BAN_TEMPORARIO, 0)
    embed.add_field(name="Bans", value=str(bans), inline=True)
    embed.add_field(name="Expulsões", value=str(counts.get(PunishmentType.KICK, 0)), inline=True)

    if punishments:
        last = punishments[0]
        embed.add_field(
            name="Última punição",
            value=(
                f"**ID:** {last.punishment_code}\n"
                f"**Tipo:** {PUNISHMENT_TYPE_LABELS[last.type]}\n"
                f"**Motivo:** {last.reason}\n"
                f"**Staff:** {last.staff_name or last.staff_id}\n"
                f"**Data:** {discord.utils.format_dt(last.created_at, style='d')}\n"
                f"**Status:** {PUNISHMENT_STATUS_LABELS[last.status]}"
            ),
            inline=False,
        )
        others = punishments[1:11]
        if others:
            embed.add_field(
                name="Outras punições",
                value="\n".join(
                    f"`{p.punishment_code}` — {PUNISHMENT_TYPE_LABELS[p.type]} "
                    f"({PUNISHMENT_STATUS_LABELS[p.status]})"
                    for p in others
                ),
                inline=False,
            )
    else:
        embed.description = "Nenhuma punição registrada."
    return embed


def pending_punishments_embed(
    page_items: list[PendingPunishmentItem],
    *,
    total_count: int,
    page: int,
    total_pages: int,
    divergent_members: list[discord.Member] | None = None,
) -> discord.Embed:
    """Usado por /analises — lista compacta (numerada) da página atual. Detalhe completo
    de cada punição fica na tela aberta via select menu (pending_punishment_detail_embed).
    `divergent_members` são membros com o cargo de análise no Discord mas sem punição
    PENDING_REVIEW correspondente no banco — só alerta, banco continua sendo a fonte."""
    embed = discord.Embed(title="🔒 PUNIÇÕES EM ANÁLISE", color=EMBED_COLOR_ORANGE)
    embed.add_field(name="Total de casos", value=str(total_count), inline=False)
    if page_items:
        lines = [
            f"{i}. <@{item.punishment.user_id}> — `{item.punishment.punishment_code}` "
            f"({PUNISHMENT_TYPE_LABELS[item.punishment.type]})"
            for i, item in enumerate(page_items, start=1)
        ]
        embed.add_field(name="Usuários aguardando decisão", value="\n".join(lines), inline=False)
        embed.add_field(
            name="Ver detalhes / decidir",
            value="Use o menu abaixo pra selecionar uma punição.",
            inline=False,
        )
    else:
        embed.description = "Nenhuma punição em análise no momento."
    if divergent_members:
        shown = divergent_members[:10]
        value = "\n".join(f"<@{m.id}>" for m in shown)
        if len(divergent_members) > len(shown):
            value += f"\n… e mais {len(divergent_members) - len(shown)}."
        embed.add_field(
            name="⚠️ Cargo sem punição no banco",
            value=value + "\n(cargo atribuído manualmente ou punição corrompida — verificar)",
            inline=False,
        )
    embed.set_footer(text=f"Página {page}/{total_pages}")
    return embed


def pending_punishment_detail_embed(
    item: PendingPunishmentItem, *, time_remaining: str | None
) -> discord.Embed:
    """Detalhe completo de 1 punição em análise, aberto via select menu do /analises."""
    punishment = item.punishment
    embed = discord.Embed(title="📋 DETALHES DA PUNIÇÃO", color=EMBED_COLOR_ORANGE)
    embed.add_field(name="Usuário", value=f"<@{punishment.user_id}>", inline=True)
    embed.add_field(name="ID", value=str(punishment.user_id), inline=True)
    embed.add_field(name="Punição", value=punishment.punishment_code, inline=False)
    embed.add_field(name="Tipo", value=PUNISHMENT_TYPE_LABELS[punishment.type], inline=True)
    embed.add_field(
        name="Aplicada por", value=punishment.staff_name or str(punishment.staff_id), inline=True
    )
    embed.add_field(name="Motivo", value=punishment.reason, inline=False)
    proofs_value = f"{len(punishment.proofs)} anexo(s)" if punishment.proofs else "Nenhuma prova anexada"
    embed.add_field(name="Provas", value=proofs_value, inline=False)
    embed.add_field(
        name="Criado em", value=discord.utils.format_dt(punishment.created_at, style="f"), inline=True
    )
    embed.add_field(name="Tempo restante", value=time_remaining or "—", inline=True)
    embed.add_field(name="Status", value=PUNISHMENT_STATUS_LABELS[punishment.status], inline=False)
    appeal_value = APPEAL_STATUS_LABELS[item.appeal.status] if item.appeal else "Nenhum recurso enviado"
    embed.add_field(name="Recurso", value=appeal_value, inline=True)
    return embed


def help_main_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🤖 LIMERENCE BOT — Central de Ajuda",
        description="Escolha uma categoria abaixo pra ver os comandos disponíveis.",
        color=EMBED_COLOR_DEFAULT,
    )
    return embed


def help_category_embed(category: str, commands: list[CommandHelp]) -> discord.Embed:
    label = HELP_CATEGORY_LABELS.get(category, category)
    embed = discord.Embed(title=label, color=EMBED_COLOR_DEFAULT)
    if not commands:
        embed.description = "Nenhum comando disponível nessa categoria pro seu nível de permissão."
        return embed
    embed.description = "\n".join(f"`/{c.command_name}` — {c.description}" for c in commands)
    embed.set_footer(text="Use /help comando:<nome> pra ver detalhes de um comando específico.")
    return embed


def help_general_embed(commands: list[tuple[str, str]]) -> discord.Embed:
    """Lista TODOS os slash commands registrados no bot (lidos direto da tree,
    nao da tabela command_help — assim novos comandos aparecem automaticamente
    sem precisar cadastrar nada), em ordem alfabetica. /config painel fica de
    fora porque suas opcoes internas sao botoes/selects, nao comandos."""
    embed = discord.Embed(
        title="📚 Todos os Comandos",
        description="Lista completa de comandos do bot, em ordem alfabética.",
        color=EMBED_COLOR_DEFAULT,
    )
    if not commands:
        embed.add_field(name="—", value="Nenhum comando encontrado.", inline=False)
        return embed

    lines = [f"`/{name}` — {description}" if description else f"`/{name}`" for name, description in commands]
    chunk: list[str] = []
    length = 0
    field_index = 1
    for line in lines:
        if chunk and (length + len(line) + 1 > 1000 or len(chunk) >= 15):
            embed.add_field(name=f"Comandos ({field_index})", value="\n".join(chunk), inline=False)
            chunk = []
            length = 0
            field_index += 1
        chunk.append(line)
        length += len(line) + 1
    if chunk:
        embed.add_field(name=f"Comandos ({field_index})", value="\n".join(chunk), inline=False)

    embed.set_footer(text=f"{len(commands)} comando(s) no total.")
    return embed


def help_command_embed(command: CommandHelp) -> discord.Embed:
    embed = discord.Embed(
        title=f"🔨 Comando: /{command.command_name}",
        description=f"**Descrição:**\n{command.description}\n\n**Uso:**\n`{command.usage}`",
        color=EMBED_COLOR_DEFAULT,
    )
    if command.examples:
        embed.add_field(
            name="Exemplos", value="\n".join(f"`{ex}`" for ex in command.examples), inline=False
        )
    embed.set_footer(text=f"Categoria: {HELP_CATEGORY_LABELS.get(command.category, command.category)}")
    return embed


def automod_status_embed(settings: AutoModSettings) -> discord.Embed:
    embed = discord.Embed(
        title="🛡️ AutoMod — configuração",
        color=EMBED_COLOR_SUCCESS if settings.enabled else EMBED_COLOR_DANGER,
    )
    embed.add_field(name="Status", value="🟢 Ativado" if settings.enabled else "🔴 Desativado", inline=False)
    embed.add_field(name="Timeout (médio risco)", value=f"{settings.medio_timeout_minutes} min", inline=True)
    embed.add_field(
        name="Alto risco",
        value=("Ban" if settings.alto_use_ban else f"Timeout {settings.alto_timeout_minutes} min"),
        inline=True,
    )
    embed.add_field(
        name="Canal de alerta", value=f"<#{settings.alert_channel_id}>" if settings.alert_channel_id else "—",
        inline=True,
    )
    embed.add_field(
        name="Canais ignorados",
        value=", ".join(f"<#{c}>" for c in settings.ignored_channel_ids) or "—",
        inline=False,
    )
    embed.add_field(
        name="Cargos ignorados",
        value=", ".join(f"<@&{r}>" for r in settings.ignored_role_ids) or "—",
        inline=False,
    )
    embed.add_field(
        name="Palavras permitidas (exceções)",
        value=", ".join(settings.allowed_words) or "—",
        inline=False,
    )
    return embed


def automod_word_list_embed(words: list[EffectiveWord]) -> discord.Embed:
    embed = discord.Embed(title="🛡️ AutoMod — palavras bloqueadas", color=EMBED_COLOR_DEFAULT)
    if not words:
        embed.description = "Nenhuma palavra configurada."
        return embed
    by_category: dict[str, list[EffectiveWord]] = {}
    for word in words:
        by_category.setdefault(word.categoria.value, []).append(word)
    for category, items in by_category.items():
        value = ", ".join(f"`{w.palavra}` ({w.nivel.value})" for w in items)
        embed.add_field(name=category, value=value[:1024], inline=False)
    embed.set_footer(text=f"{len(words)} palavra(s) ativa(s).")
    return embed


def automod_log_list_embed(entries: list[AutoModLog]) -> discord.Embed:
    embed = discord.Embed(title="🛡️ AutoMod — histórico de ações", color=EMBED_COLOR_DEFAULT)
    if not entries:
        embed.description = "Nenhuma ação registrada ainda."
        return embed
    for entry in entries[:15]:
        embed.add_field(
            name=f"{entry.created_at.strftime('%d/%m/%Y %H:%M')} — {entry.user_name or entry.user_id}",
            value=(
                f"Termo: `{entry.palavra_detectada}` | Categoria: {entry.categoria.value} | "
                f"Nível: {entry.nivel.value} | Ação: {entry.punicao_aplicada}"
            ),
            inline=False,
        )
    embed.set_footer(text=f"Mostrando {min(len(entries), 15)} de {len(entries)} registro(s).")
    return embed


def booster_added_log_embed(
    member: discord.Member, role: discord.Role | None, boost_count: int
) -> discord.Embed:
    embed = discord.Embed(title="💜 Booster Adicionado", color=EMBED_COLOR_PURPLE)
    embed.add_field(name="Usuário", value=f"{member.mention} ({member.id})", inline=False)
    embed.add_field(name="Cargo entregue", value=role.mention if role else "—", inline=True)
    embed.add_field(name="Servidor", value=member.guild.name, inline=True)
    embed.add_field(name="Boosts acumulados", value=str(boost_count), inline=True)
    embed.timestamp = discord.utils.utcnow()
    return embed


def booster_removed_log_embed(
    member: discord.Member, role: discord.Role | None, duration_seconds: int | None
) -> discord.Embed:
    embed = discord.Embed(title="💔 Booster Removido", color=EMBED_COLOR_DARK)
    embed.add_field(name="Usuário", value=f"{member.mention} ({member.id})", inline=False)
    embed.add_field(name="Cargo removido", value=role.mention if role else "—", inline=True)
    embed.add_field(name="Servidor", value=member.guild.name, inline=True)
    embed.add_field(name="Tempo impulsionando", value=humanize_duration(duration_seconds), inline=True)
    embed.timestamp = discord.utils.utcnow()
    return embed


def verification_prompt_embed(description: str, *, code: str) -> discord.Embed:
    embed = discord.Embed(title="🛡️ Verificação Necessária", description=description, color=EMBED_COLOR_VIOLET)
    embed.add_field(name="Código", value=f"`{code}`", inline=False)
    embed.set_footer(text="Verificação • Limerence")
    return embed


def verification_log_embed(
    *,
    user_id: int,
    method_label: str,
    attempts_used: int,
    max_attempts: int,
    elapsed_label: str,
    result_label: str,
) -> discord.Embed:
    embed = discord.Embed(title="🛡️ Verificação", color=EMBED_COLOR_VIOLET)
    embed.add_field(name="Usuário", value=f"<@{user_id}> ({user_id})", inline=False)
    embed.add_field(name="Método", value=method_label, inline=True)
    embed.add_field(name="Tentativas", value=f"{attempts_used}/{max_attempts}", inline=True)
    embed.add_field(name="Tempo para concluir", value=elapsed_label, inline=True)
    embed.add_field(name="Resultado", value=result_label, inline=False)
    embed.timestamp = discord.utils.utcnow()
    return embed


def poll_creation_embed(poll: Poll, options: list[PollOption]) -> discord.Embed:
    embed = discord.Embed(title=f"🗳️ {poll.title}", description=poll.description or None, color=EMBED_COLOR_DEFAULT)
    for option in options:
        embed.add_field(name=option.name, value="​", inline=False)
    embed.add_field(name="Criado por", value=f"<@{poll.creator_id}>", inline=True)
    embed.add_field(name="Encerra em", value=discord.utils.format_dt(poll.expires_at, style="R"), inline=True)
    embed.set_footer(text="Clique num botão abaixo pra votar. 1 voto por pessoa.")
    return embed


def poll_results_embed(
    poll: Poll,
    options: list[PollOption],
    weighted_totals: dict,
    participant_count: int,
) -> discord.Embed:
    embed = discord.Embed(title=f"🗳️ Resultado — {poll.title}", color=EMBED_COLOR_PURPLE)
    max_total = max(weighted_totals.values(), default=0)
    for option in options:
        total = weighted_totals.get(option.id, 0)
        marker = "🏆 " if total == max_total and max_total > 0 else ""
        embed.add_field(name=f"{marker}{option.name}", value=f"{total} voto(s) ponderado(s)", inline=False)
    embed.set_footer(text=f"{participant_count} participante(s) — encerrada.")
    embed.timestamp = discord.utils.utcnow()
    return embed
