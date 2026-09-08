from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord

from database.models.audit_log import AuditLogCategory
from database.models.automod import AutoModLog, AutoModSettings
from database.models.command_help import CommandHelp
from database.models.evaluation_settings import EvaluationSettings
from database.models.giveaway import Giveaway, GiveawayPrizeType
from database.models.log import LogAction
from database.models.partnership import Partnership
from database.models.payment import PaymentHistory
from database.models.payment_dm_settings import PaymentDmSettings
from database.models.plan import Plan
from database.models.poll import Poll, PollOption, PollStatus
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
from utils.poll_style import option_dot
from utils.time import humanize_duration

if TYPE_CHECKING:
    from services.punishment_review_service import PendingPunishmentItem


TICKET_STATUS_LABELS: dict[str, str] = {
    "open": "🟢 Aberto",
    "claimed": "🟡 Em atendimento",
    "closed": "🔴 Fechado",
}


def ticket_panel_status_label(ticket: Ticket) -> str:
    return TICKET_STATUS_LABELS.get(ticket.status.value, TICKET_STATUS_LABELS["open"])


def ticket_embed(
    ticket: Ticket,
    opener: discord.Member | discord.User,
    panel: TicketPanel | None = None,
    *,
    claimed_staff_name: str | None = None,
) -> discord.Embed:
    """Painel enviado dentro do canal do ticket — o mesmo pra qualquer
    categoria (Suporte, Painel Parceria, ...): titulo/descricao/cor/footer
    vem 100% da config do painel quando existe (`panel.embed_*`), nada aqui e
    fixo por categoria. Status/Assumido por/Aberto sao sempre recalculados a
    partir do `ticket` — reflete o estado real toda vez que a embed e
    reconstruida (claim/unclaim/incluir/remover chamam isto de novo)."""
    if panel is not None:
        panel_emoji = panel.button_emoji or "📁"
        title = f"{panel_emoji} {panel.name} — {opener.display_name}"
        description = panel.embed_description or (
            "Obrigado por abrir um ticket!\n\n"
            "Descreva seu problema e um membro da equipe irá ajudá-lo em breve."
        )
        color = (
            discord.Color(panel.embed_color) if panel.embed_color is not None else EMBED_COLOR_DEFAULT
        )
    else:
        title = f"{CATEGORY_LABELS[ticket.category]} — {opener.display_name}"
        description = (
            "Obrigado por abrir um ticket!\n\n"
            "Descreva seu problema e um membro da equipe irá ajudá-lo em breve."
        )
        color = EMBED_COLOR_DEFAULT

    embed = discord.Embed(title=title, description=description, color=color)
    embed.add_field(name="Status", value=ticket_panel_status_label(ticket), inline=True)
    embed.add_field(name="Criado por", value=opener.mention, inline=True)
    embed.add_field(
        name="Assumido por", value=claimed_staff_name or "Não assumido", inline=True
    )
    embed.add_field(
        name="Aberto",
        value=discord.utils.format_dt(ticket.created_at, style="R"),
        inline=True,
    )
    footer = panel.embed_footer if panel is not None and panel.embed_footer else None
    embed.set_footer(text=footer or f"Tickets • Limerence © {datetime.now(UTC).year}")
    if panel is not None and panel.embed_thumbnail_url:
        embed.set_thumbnail(url=panel.embed_thumbnail_url)
    return embed


DEFAULT_EVALUATION_DM_TITLE = "📁 O teu ticket foi fechado"
DEFAULT_EVALUATION_DM_DESCRIPTION = "Obrigado por entrar em contato com nossa equipe."
DEFAULT_EVALUATION_DM_PROMPT = (
    "⭐ Como foi sua experiência?\n\nSua avaliação nos ajuda a melhorar nosso atendimento."
)
DEFAULT_EVALUATION_DM_BUTTON_LABEL = "⭐ Avaliar atendimento"
DEFAULT_EVALUATION_THANKS_MESSAGE = (
    "✅ Obrigado pela sua avaliação!\n\nSeu feedback foi registrado com sucesso."
)


def ticket_type_label(ticket: Ticket, panel: TicketPanel | None) -> str:
    return panel.name if panel is not None else CATEGORY_LABELS[ticket.category]


def _evaluation_placeholder_kwargs(
    *,
    guild: discord.Guild,
    ticket: Ticket,
    panel: TicketPanel | None,
    opener: discord.Member | discord.User,
    claimed_by_name: str,
    closed_by_name: str,
) -> dict[str, object]:
    return {
        "member": opener,
        "guild": guild,
        "ticket_type": ticket_type_label(ticket, panel),
        "claimed_by": claimed_by_name,
        "closed_by": closed_by_name,
        "opened_at": discord.utils.format_dt(ticket.created_at, style="F"),
        "closed_at": (
            discord.utils.format_dt(ticket.closed_at, style="F") if ticket.closed_at else "—"
        ),
        "ticket_id": str(ticket.id)[:8],
        "reason": None,
    }


def ticket_closed_summary_embed(
    *,
    guild: discord.Guild,
    ticket: Ticket,
    panel: TicketPanel | None,
    closed_by_mention: str,
    closed_by_name: str,
    claimed_by_name: str,
) -> discord.Embed:
    embed = discord.Embed(
        title="✅ Ticket fechado",
        description=f"Fechado por {closed_by_mention}.",
        color=EMBED_COLOR_DANGER,
    )
    embed.add_field(name="Servidor", value=guild.name, inline=True)
    embed.add_field(name="Tipo", value=ticket_type_label(ticket, panel), inline=True)
    embed.add_field(name="Assumido por", value=claimed_by_name, inline=True)
    embed.add_field(name="Fechado por", value=closed_by_name, inline=True)
    embed.add_field(
        name="Aberto em", value=discord.utils.format_dt(ticket.created_at, style="F"), inline=True
    )
    embed.add_field(
        name="Fechado em",
        value=discord.utils.format_dt(ticket.closed_at, style="F") if ticket.closed_at else "—",
        inline=True,
    )
    embed.add_field(name="ID do ticket", value=f"`{str(ticket.id)[:8]}`", inline=True)
    embed.add_field(name="Motivo", value="—", inline=False)
    return embed


def evaluation_dm_embed(
    eval_settings: EvaluationSettings,
    *,
    guild: discord.Guild,
    ticket: Ticket,
    panel: TicketPanel | None,
    opener: discord.Member | discord.User,
    claimed_by_name: str,
    closed_by_name: str,
) -> discord.Embed:
    kwargs = _evaluation_placeholder_kwargs(
        guild=guild,
        ticket=ticket,
        panel=panel,
        opener=opener,
        claimed_by_name=claimed_by_name,
        closed_by_name=closed_by_name,
    )
    title = render_placeholders(eval_settings.dm_embed_title or DEFAULT_EVALUATION_DM_TITLE, **kwargs)
    description = render_placeholders(
        eval_settings.dm_embed_description or DEFAULT_EVALUATION_DM_DESCRIPTION, **kwargs
    )
    prompt = render_placeholders(eval_settings.dm_prompt_text or DEFAULT_EVALUATION_DM_PROMPT, **kwargs)

    embed = discord.Embed(title=title[:256], color=EMBED_COLOR_DEFAULT)
    embed.description = "\n\n".join(
        [
            description,
            f"**Servidor:** {kwargs['guild'].name}",  # type: ignore[union-attr]
            f"**Tipo:** {kwargs['ticket_type']}",
            f"**Assumido por:** {kwargs['claimed_by']}",
            f"**Fechado por:** {kwargs['closed_by']}",
            f"**Aberto em:** {kwargs['opened_at']}",
            f"**Fechado em:** {kwargs['closed_at']}",
            f"**ID do ticket:** `{kwargs['ticket_id']}`",
            f"**Motivo:**\n{'—'}",
            "─" * 20,
            prompt,
            f"**{evaluation_button_label(eval_settings)}**",
        ]
    )[:4096]
    embed.set_footer(text=f"Tickets • Limerence © {datetime.now(UTC).year}")
    return embed


def evaluation_button_label(eval_settings: EvaluationSettings) -> str:
    return (eval_settings.dm_button_label or DEFAULT_EVALUATION_DM_BUTTON_LABEL)[:80]


def evaluation_thanks_message(eval_settings: EvaluationSettings, **placeholder_kwargs: object) -> str:
    template = eval_settings.dm_thanks_message or DEFAULT_EVALUATION_THANKS_MESSAGE
    return render_placeholders(template, **placeholder_kwargs) if placeholder_kwargs else template


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


def _format_executor(executor_id: int | None, executor_name: str | None) -> str:
    if executor_id is None or executor_id <= 0:
        return executor_name or "Desconhecido"
    return f"<@{executor_id}>"


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
    embed.add_field(name="Executor", value=_format_executor(executor_id, executor_name), inline=True)
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
            "Envie o comprovante novamente ou fale com a equipe para conferência manual.\n\n"
            "Equipe {guild}"
        ),
    },
}


def payment_dm_embed(
    template: PaymentDmSettings,
    *,
    approved: bool,
    guild: discord.Guild,
    user: discord.User | discord.Member,
    plan: Plan,
    payment: PaymentHistory,
) -> discord.Embed:
    defaults = PAYMENT_DM_DEFAULTS[approved]
    kwargs = {"guild": guild, "user": user, "plan": plan.name, "payment": payment}
    title = render_placeholders(
        (template.approved_title if approved else template.rejected_title) or defaults["title"], **kwargs
    )
    description = render_placeholders(
        (template.approved_description if approved else template.rejected_description) or defaults["description"],
        **kwargs,
    )
    embed = discord.Embed(
        title=title[:256],
        description=description[:4096],
        color=EMBED_COLOR_SUCCESS if approved else EMBED_COLOR_DANGER,
    )
    embed.set_footer(text=f"Limerence • {datetime.now(UTC).year}")
    return embed


def plan_public_embed(plan: Plan) -> discord.Embed:
    embed = discord.Embed(title=plan.name, description=plan.description, color=EMBED_COLOR_PURPLE)
    embed.add_field(name="Valor", value=f"R$ {plan.price_one_time:.2f}", inline=True)
    embed.add_field(name="Cargo", value=f"<@&{plan.role_id}>" if plan.role_id else "—", inline=True)
    return embed


def _giveaway_prize_label(giveaway: Giveaway) -> str:
    if giveaway.prize_type == GiveawayPrizeType.ROLE and giveaway.prize_role_id is not None:
        return f"Cargo <@&{giveaway.prize_role_id}>"
    return giveaway.prize_text or "—"


def giveaway_panel_embed(giveaway: Giveaway, entry_count: int) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎉 {giveaway.title}",
        description=giveaway.description or None,
        color=EMBED_COLOR_PURPLE,
    )
    embed.add_field(name="Prêmio", value=_giveaway_prize_label(giveaway), inline=True)
    embed.add_field(name="Vencedores", value=str(giveaway.winners_count), inline=True)
    embed.add_field(name="Participantes", value=str(entry_count), inline=True)
    if giveaway.allowed_role_ids:
        roles = ", ".join(f"<@&{rid}>" for rid in giveaway.allowed_role_ids)
        embed.add_field(name="Quem pode participar", value=roles, inline=False)
    else:
        embed.add_field(name="Quem pode participar", value="Todo mundo", inline=False)
    embed.add_field(name="Encerra em", value=discord.utils.format_dt(giveaway.expires_at, style="R"), inline=True)
    embed.set_footer(text="Clique em Participar abaixo. 1 participação por pessoa.")
    return embed


def giveaway_result_embed(giveaway: Giveaway, winner_ids: list[int], *, is_reroll: bool) -> discord.Embed:
    title_prefix = "🔁 Novo sorteio" if is_reroll else "🎉 Resultado"
    embed = discord.Embed(title=f"{title_prefix} — {giveaway.title}", color=EMBED_COLOR_SUCCESS)
    if winner_ids:
        embed.add_field(
            name="Vencedor(es)", value="\n".join(f"<@{uid}>" for uid in winner_ids), inline=False
        )
    else:
        embed.add_field(name="Vencedor(es)", value="Ninguém participou desse sorteio.", inline=False)
    embed.add_field(name="Prêmio", value=_giveaway_prize_label(giveaway), inline=True)
    embed.timestamp = discord.utils.utcnow()
    return embed
