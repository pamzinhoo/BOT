from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands

if TYPE_CHECKING:
    from core.bot import LimerenceBot

PAGE_SIZE = 10

_PERIOD_DELTAS: dict[str, timedelta | None] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "tudo": None,
}

CONFIG_HISTORY_PERIOD_CHOICES = [app_commands.Choice(name=p, value=p) for p in _PERIOD_DELTAS]

_CATEGORIES = ["Tickets", "Cargos", "Permissões", "Dashboard", "Ranking", "Avaliações", "Anti-Spam", "Alertas", "Auditoria"]
CONFIG_HISTORY_CATEGORY_CHOICES = [app_commands.Choice(name=c, value=c) for c in _CATEGORIES]


@dataclass(frozen=True)
class ConfigHistoryFilters:
    usuario_id: int | None = None
    categoria: str | None = None
    configuracao: str | None = None
    periodo: str | None = None
    page: int = 0


def _since(periodo: str | None) -> datetime | None:
    delta = _PERIOD_DELTAS.get(periodo) if periodo else None
    return datetime.now(UTC) - delta if delta else None


async def render_config_history(
    bot: "LimerenceBot", guild_id: int, filters: ConfigHistoryFilters
) -> tuple[discord.Embed, int]:
    """Busca a pagina atual + total de registros. Retorna (embed, total_paginas)."""
    since = _since(filters.periodo)
    total = await bot.audit_log_service.count_entries(
        guild_id,
        executor_id=filters.usuario_id,
        config_category=filters.categoria,
        config_name=filters.configuracao,
        since=since,
    )
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(filters.page, total_pages - 1)

    entries = await bot.audit_log_service.list_entries(
        guild_id,
        executor_id=filters.usuario_id,
        config_category=filters.categoria,
        config_name=filters.configuracao,
        since=since,
        limit=PAGE_SIZE,
        offset=page * PAGE_SIZE,
    )

    embed = discord.Embed(title="🕵️ Histórico de Configuração")
    if not entries:
        embed.description = "Nenhuma alteração encontrada com esses filtros."
    else:
        for entry in entries:
            executor = f"<@{entry.executor_id}>" if entry.executor_id else (entry.executor_name or "Desconhecido")
            timestamp = discord.utils.format_dt(entry.created_at, style="f")
            embed.add_field(
                name=f"{entry.config_category or '—'} · {entry.config_name or '—'}",
                value=(
                    f"Executor: {executor}\n"
                    f"Antes: {entry.old_value or '—'}\n"
                    f"Depois: {entry.new_value or '—'}\n"
                    f"{timestamp}"
                ),
                inline=False,
            )
    embed.set_footer(text=f"Página {page + 1}/{total_pages} — {total} registro(s)")
    return embed, total_pages


class ConfigHistoryView(discord.ui.View):
    """Paginador do /config history. Nao-persistente (timeout=300) — utilitario de
    admin aberto sob demanda, edita sempre a mesma mensagem."""

    def __init__(self, filters: ConfigHistoryFilters, total_pages: int) -> None:
        super().__init__(timeout=300)
        self.filters = filters
        self.total_pages = total_pages
        self._previous.disabled = filters.page <= 0
        self._next.disabled = filters.page >= total_pages - 1

    @discord.ui.button(label="◀ Anterior", style=discord.ButtonStyle.secondary)
    async def _previous(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._go(interaction, self.filters.page - 1)

    @discord.ui.button(label="Próxima ▶", style=discord.ButtonStyle.secondary)
    async def _next(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._go(interaction, self.filters.page + 1)

    async def _go(self, interaction: discord.Interaction, page: int) -> None:
        assert interaction.guild_id is not None
        bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
        filters = replace(self.filters, page=max(0, page))
        embed, total_pages = await render_config_history(bot, interaction.guild_id, filters)
        await interaction.response.edit_message(
            embed=embed, view=ConfigHistoryView(filters, total_pages)
        )
