from __future__ import annotations

import asyncio
import io

import discord

from database.database import Database
from database.repositories.dashboard_settings_repository import DashboardSettingsRepository
from database.repositories.guild_settings_repository import GuildSettingsRepository
from database.repositories.monetization_settings_repository import MonetizationSettingsRepository
from database.repositories.ranking_settings_repository import RankingSettingsRepository
from database.repositories.ticket_repository import TicketRepository
from services.ranking_service import RankingEntry, RankingPeriod, RankingService
from utils.constants import EMBED_COLOR_DEFAULT
from utils.dashboard_chart import render_ranking_chart
from utils.formatter import rank_marker


def _sort_by_criteria(entries: list[RankingEntry], criteria: str) -> list[RankingEntry]:
    if criteria == "avaliacao":
        return sorted(entries, key=lambda e: (e.avaliacao_media, e.tickets), reverse=True)
    return sorted(entries, key=lambda e: (e.tickets, e.avaliacao_media), reverse=True)


class PainelService:
    """Atualiza o dashboard da staff e a mensagem de ranking (canais separados
    do painel publico de abertura de ticket) a cada evento (claim/fechamento/
    avaliacao/reabertura), nunca por agendamento — ranking sempre lido
    on-the-fly de staff_stats.
    """

    def __init__(self, database: Database, bot: discord.Client) -> None:
        self._database = database
        self._bot = bot
        self._ranking_service = RankingService(database)

    async def refresh_dashboard(self, guild_id: int) -> None:
        async with self._database.session() as session:
            settings = await GuildSettingsRepository(session).get_by_guild_id(guild_id)
            if settings is None:
                return
            open_tickets = await TicketRepository(session).list_open_by_guild(guild_id)
            dashboard_channel_id = settings.dashboard_channel_id
            dashboard_message_id = settings.dashboard_message_id
            ranking_channel_id = settings.ranking_channel_id
            ranking_message_id = settings.ranking_message_id
            dashboard_settings = await DashboardSettingsRepository(session).get_or_create(guild_id)
            ranking_settings = await RankingSettingsRepository(session).get_or_create(guild_id)
            top_count = dashboard_settings.top_count
            show_chart = dashboard_settings.show_chart
            criteria = ranking_settings.criteria

        ranking = _sort_by_criteria(
            await self._ranking_service.compute(guild_id, RankingPeriod.ALLTIME), criteria
        )

        if dashboard_channel_id is not None and dashboard_message_id is not None:
            await self._refresh_dashboard_message(
                dashboard_channel_id,
                dashboard_message_id,
                len(open_tickets),
                ranking[:top_count],
                show_chart,
            )

        if ranking_channel_id is not None:
            await self._refresh_ranking_message(guild_id, ranking_channel_id, ranking_message_id, ranking)

    async def _refresh_dashboard_message(
        self,
        channel_id: int,
        message_id: int,
        open_count: int,
        top_entries: list[RankingEntry],
        show_chart: bool,
    ) -> None:
        channel = self._bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            return

        embed = discord.Embed(title="📊 Painel da Staff", color=EMBED_COLOR_DEFAULT)
        embed.add_field(name="🎫 Tickets Abertos", value=str(open_count), inline=True)
        lines = [
            f"{rank_marker(i)} {entry.staff.display_name} — {entry.tickets}"
            for i, entry in enumerate(top_entries)
        ]
        embed.add_field(
            name=f"🏆 TOP {len(top_entries) or ''}".strip(),
            value="\n".join(lines) or "Sem dados ainda.",
            inline=False,
        )

        if top_entries and show_chart:
            # matplotlib e sincrono/CPU-bound — chamado direto travaria o bot
            # inteiro (todas as guilds, inclusive verificacao/interacoes em
            # andamento) pelo tempo de renderizacao, e isso acontece toda vez
            # que o dashboard atualiza (a cada evento + a cada 1min por guild).
            chart_bytes = await asyncio.to_thread(render_ranking_chart, top_entries)
            chart_file = discord.File(io.BytesIO(chart_bytes), filename="ranking.png")
            embed.set_image(url="attachment://ranking.png")
            await message.edit(embed=embed, attachments=[chart_file])
        else:
            await message.edit(embed=embed, attachments=[])

    async def _refresh_ranking_message(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int | None,
        ranking: list[RankingEntry],
    ) -> None:
        channel = self._bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        embed = discord.Embed(title="🏆 Ranking — Geral", color=EMBED_COLOR_DEFAULT)
        if not ranking:
            embed.description = "Sem dados suficientes ainda."
        else:
            lines = [
                f"{rank_marker(i)} {entry.staff.display_name} — {entry.tickets} tickets, "
                f"⭐ {entry.avaliacao_media:.1f}"
                for i, entry in enumerate(ranking[:10])
            ]
            embed.description = "\n".join(lines)

        message = None
        if message_id is not None:
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                message = None

        if message is not None:
            await message.edit(embed=embed)
            return

        # sem mensagem valida (primeira vez ou foi apagada) — posta uma nova e salva o id
        new_message = await channel.send(embed=embed)
        async with self._database.session() as session:
            settings = await GuildSettingsRepository(session).get_or_create(guild_id)
            settings.ranking_message_id = new_message.id

    # --- painel fixo da loja (auto-atualiza quando os planos mudam) ---------

    async def publish_shop_panel(self, guild_id: int, channel_id: int) -> None:
        """Posta (ou reposta, se o canal mudou) o painel fixo da loja nesse
        canal e salva canal+mensagem em MonetizationSettings."""
        channel = self._bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        from views.shop_view import ShopPanelView, shop_panel_embed

        plans = await self._bot.plan_service.list_plans(guild_id, only_active=True)
        message = await channel.send(embed=shop_panel_embed(plans), view=ShopPanelView())
        async with self._database.session() as session:
            settings = await MonetizationSettingsRepository(session).get_or_create(guild_id)
            settings.shop_channel_id = channel_id
            settings.shop_message_id = message.id

    async def refresh_shop_panel(self, guild_id: int) -> None:
        """Re-renderiza o painel fixo da loja ja publicado — chamado sempre
        que um plano e criado/editado/removido. Nunca reposta sozinho (se a
        mensagem foi apagada, precisa publicar de novo via /loja ou /config)."""
        async with self._database.session() as session:
            settings = await MonetizationSettingsRepository(session).get_by_guild_id(guild_id)
        if settings is None or settings.shop_channel_id is None or settings.shop_message_id is None:
            return
        channel = self._bot.get_channel(settings.shop_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(settings.shop_message_id)
        except discord.NotFound:
            return

        from views.shop_view import shop_panel_embed

        plans = await self._bot.plan_service.list_plans(guild_id, only_active=True)
        try:
            await message.edit(embed=shop_panel_embed(plans))
        except discord.HTTPException:
            pass
