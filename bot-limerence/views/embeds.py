from __future__ import annotations

import discord

from database.models.audit_log import AuditLogCategory
from database.models.log import LogAction
from database.models.staff_stats import StaffStats
from database.models.ticket import Ticket, TicketCategory
from services.ranking_service import RankingEntry
from services.staff_service import StaffProfile
from utils.constants import (
    AUDIT_CATEGORY_COLORS,
    AUDIT_CATEGORY_LABELS,
    AUDIT_CATEGORY_TARGET_KIND,
    CATEGORY_CONFIRM_TEXT,
    CATEGORY_LABELS,
    EMBED_COLOR_DEFAULT,
    LOG_ACTION_LABELS,
    achievement_label,
)
from utils.formatter import rank_marker
from utils.time import humanize_duration


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


def open_ticket_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🎫 Suporte",
        description=(
            "Selecione uma categoria abaixo para abrir um ticket com a nossa equipe de suporte."
        ),
        color=EMBED_COLOR_DEFAULT,
    )
    return embed


def category_select_options() -> list[discord.SelectOption]:
    return [
        discord.SelectOption(label=label, value=category.value)
        for category, label in CATEGORY_LABELS.items()
    ]


def category_from_value(value: str) -> TicketCategory:
    return TicketCategory(value)
