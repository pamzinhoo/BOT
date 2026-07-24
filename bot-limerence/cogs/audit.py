from __future__ import annotations

from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import LimerenceBot
from database.models.audit_log import AuditLogCategory
from utils.checks import has_permission
from utils.constants import AUDIT_CATEGORY_LABELS, AUDIT_CATEGORY_TARGET_KIND

_PERIOD_DELTAS: dict[str, timedelta | None] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "tudo": None,
}

_CATEGORY_CHOICES = [
    app_commands.Choice(name=label, value=category.value)
    for category, label in AUDIT_CATEGORY_LABELS.items()
]


class AuditCog(commands.Cog):
    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    @app_commands.command(name="audit", description="Consulta os logs de auditoria do servidor.")
    @app_commands.describe(
        usuario="Filtrar pelo alvo da ação",
        staff="Filtrar por quem executou a ação",
        categoria="Filtrar por categoria",
        acao="Filtrar por texto na ação (ex: 'banido')",
        periodo="Janela de tempo (padrão: tudo)",
    )
    @app_commands.choices(
        categoria=_CATEGORY_CHOICES,
        periodo=[app_commands.Choice(name=p, value=p) for p in _PERIOD_DELTAS],
    )
    @has_permission("auditoria")
    async def audit(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member | None = None,
        staff: discord.Member | None = None,
        categoria: app_commands.Choice[str] | None = None,
        acao: str | None = None,
        periodo: app_commands.Choice[str] | None = None,
    ) -> None:
        assert interaction.guild_id is not None
        delta = _PERIOD_DELTAS[periodo.value] if periodo else None
        since = datetime.now(UTC) - delta if delta else None

        entries = await self.bot.audit_log_service.list_entries(
            interaction.guild_id,
            target_id=usuario.id if usuario else None,
            executor_id=staff.id if staff else None,
            category=AuditLogCategory(categoria.value) if categoria else None,
            action=acao,
            since=since,
            limit=20,
        )

        if not entries:
            await interaction.response.send_message("Nenhum registro encontrado.", ephemeral=True)
            return

        lines = []
        for entry in entries:
            timestamp = discord.utils.format_dt(entry.created_at, style="f")
            executor = f"<@{entry.executor_id}>" if entry.executor_id else (entry.executor_name or "Desconhecido")
            target_kind = AUDIT_CATEGORY_TARGET_KIND.get(entry.category, "user")
            if entry.target_id is None:
                target = entry.target_name or "—"
            elif target_kind == "channel":
                target = f"<#{entry.target_id}>"
            elif target_kind == "role":
                target = f"<@&{entry.target_id}>"
            elif target_kind == "none":
                target = entry.target_name or str(entry.target_id)
            else:
                target = f"<@{entry.target_id}>"
            reason = f" ({entry.reason})" if entry.reason else ""
            lines.append(
                f"{timestamp} **{AUDIT_CATEGORY_LABELS[entry.category]}** — {executor} → {target}{reason}"
            )

        embed = discord.Embed(
            title="🕵️ Logs de auditoria",
            description="\n".join(lines)[:4000],
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(AuditCog(bot))
