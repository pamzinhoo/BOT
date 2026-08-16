from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import discord

from database.models.ticket import Ticket, TicketCategory, TicketStatus
from database.models.ticket_panel import TicketPanel
from database.models.ticket_settings import DEFAULT_CATEGORY_SELECTION_MODE
from services.config_transfer_service import TABLE_SCHEMAS, build_import_plan
from services.ticket_panel_service import (
    MAX_SELECT_OPTIONS,
    chunk_panels_for_selects,
    normalize_selection_mode,
    panels_over_capacity,
    selectable_panels,
    selection_capacity,
)
from views.embeds import ticket_embed, ticket_panel_status_label
from views.ticket_actions_view import TicketActionsView
from views.ticket_panel_open_view import (
    TicketPanelGroupOpenView,
    _OpenTicketSelect,
    panel_select_option,
)


def _panel(guild_id: int, key: str, name: str, *, show_button: bool = True) -> TicketPanel:
    panel = TicketPanel(guild_id=guild_id, key=key, name=name, show_button=show_button)
    panel.id = uuid.uuid4()
    return panel


def _ticket(*, claimed_by: uuid.UUID | None = None, status: TicketStatus = TicketStatus.OPEN) -> Ticket:
    ticket = Ticket(
        guild_id=1,
        channel_id=999,
        opened_by_discord_id=42,
        category=TicketCategory.OUTRO,
        status=status,
        claimed_by_staff_id=claimed_by,
        created_at=datetime.now(UTC),
    )
    ticket.id = uuid.uuid4()
    return ticket


# =========================== metodo de selecao ==============================


def test_normalize_selection_mode_defaults_unknown_to_buttons() -> None:
    assert normalize_selection_mode(None) == DEFAULT_CATEGORY_SELECTION_MODE
    assert normalize_selection_mode("nao-existe") == "buttons"
    assert normalize_selection_mode("select") == "select"


def test_selection_capacity_buttons_vs_select() -> None:
    assert selection_capacity("buttons") == 25
    assert selection_capacity("select") == 125  # 25 opcoes x 5 selects


def test_selectable_panels_excludes_show_button_false() -> None:
    visible = _panel(1, "suporte", "Suporte")
    hidden = _panel(1, "principal", "Painel Central", show_button=False)
    assert selectable_panels([visible, hidden]) == [visible]


def test_chunk_panels_for_selects_splits_at_25_and_caps_at_5_blocks() -> None:
    panels = [_panel(1, f"cat-{i}", f"Categoria {i}") for i in range(130)]
    chunks = chunk_panels_for_selects(panels)
    assert len(chunks) == 5
    assert all(len(chunk) <= MAX_SELECT_OPTIONS for chunk in chunks)
    assert sum(len(chunk) for chunk in chunks) == 125


def test_panels_over_capacity_reports_excess_without_dropping_silently() -> None:
    panels = [_panel(1, f"cat-{i}", f"Categoria {i}") for i in range(30)]
    excess = panels_over_capacity(panels, "buttons")
    assert len(excess) == 5  # 30 - 25
    assert panels_over_capacity(panels, "select") == []  # cabe nos 125 do select


def test_panel_select_option_uses_real_panel_config() -> None:
    panel = _panel(1, "suporte", "Suporte")
    panel.button_label = "Abrir Suporte"
    panel.button_emoji = "🛠️"
    panel.embed_description = "Fale com o suporte."
    option = panel_select_option(panel)
    assert option.value == "suporte"
    assert option.label == "Abrir Suporte"
    assert str(option.emoji) == "🛠️"
    assert option.description == "Fale com o suporte."


def test_group_open_view_uses_buttons_by_default() -> None:
    panels = [_panel(1, "suporte", "Suporte"), _panel(1, "parceria", "Parceria")]
    view = TicketPanelGroupOpenView(panels, "buttons")
    assert all(isinstance(item, discord.ui.Button) for item in view.children)
    assert len(view.children) == 2


def test_group_open_view_uses_select_when_configured() -> None:
    panels = [_panel(1, "suporte", "Suporte"), _panel(1, "parceria", "Parceria")]
    view = TicketPanelGroupOpenView(panels, "select")
    assert len(view.children) == 1
    assert isinstance(view.children[0], _OpenTicketSelect)
    assert {opt.value for opt in view.children[0].options} == {"suporte", "parceria"}


def test_group_open_view_select_splits_across_multiple_menus_over_25() -> None:
    panels = [_panel(1, f"cat-{i}", f"Categoria {i}") for i in range(40)]
    view = TicketPanelGroupOpenView(panels, "select")
    assert len(view.children) == 2
    assert len(view.children[0].options) == 25
    assert len(view.children[1].options) == 15


def test_group_open_view_skips_panels_with_show_button_false() -> None:
    main = _panel(1, "principal", "Painel Central", show_button=False)
    child = _panel(1, "suporte", "Suporte")
    view = TicketPanelGroupOpenView([main, child], "select")
    assert len(view.children) == 1
    assert {opt.value for opt in view.children[0].options} == {"suporte"}


# ============================ painel do ticket ==============================


def test_ticket_embed_shows_open_and_unclaimed_by_default() -> None:
    ticket = _ticket()
    opener = MagicMock(spec=discord.Member)
    opener.mention = "<@42>"
    opener.display_name = "Pam"
    embed = ticket_embed(ticket, opener)
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Status"] == "🟢 Aberto"
    assert fields["Assumido por"] == "Não assumido"
    assert "Pam" in embed.title


def test_ticket_embed_reflects_claim() -> None:
    staff_id = uuid.uuid4()
    ticket = _ticket(claimed_by=staff_id, status=TicketStatus.CLAIMED)
    opener = MagicMock(spec=discord.Member)
    opener.mention = "<@42>"
    opener.display_name = "Pam"
    embed = ticket_embed(ticket, opener, claimed_staff_name="StaffX")
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Status"] == "🟡 Em atendimento"
    assert fields["Assumido por"] == "StaffX"


def test_ticket_embed_uses_panel_name_and_description() -> None:
    ticket = _ticket()
    opener = MagicMock(spec=discord.Member)
    opener.mention = "<@42>"
    opener.display_name = "Pam"
    panel = _panel(1, "parceria", "Painel Parceria")
    panel.button_emoji = "🤝"
    panel.embed_description = "Descreva sua proposta de parceria."
    embed = ticket_embed(ticket, opener, panel)
    assert embed.title == "🤝 Painel Parceria — Pam"
    assert embed.description == "Descreva sua proposta de parceria."


def test_ticket_panel_status_label_covers_all_rendered_statuses() -> None:
    assert ticket_panel_status_label(_ticket(status=TicketStatus.OPEN)) == "🟢 Aberto"
    assert ticket_panel_status_label(_ticket(status=TicketStatus.CLAIMED)) == "🟡 Em atendimento"
    assert ticket_panel_status_label(_ticket(status=TicketStatus.CLOSED)) == "🔴 Fechado"


# ============================ TicketActionsView ==============================


def _custom_ids(view: discord.ui.View) -> set[str]:
    return {item.custom_id for item in view.children if hasattr(item, "custom_id")}


def test_actions_view_shows_claim_when_unclaimed() -> None:
    view = TicketActionsView(_ticket())
    ids = _custom_ids(view)
    assert "limerence:ticket:claim" in ids
    assert "limerence:ticket:unclaim" not in ids


def test_actions_view_shows_unclaim_when_claimed() -> None:
    view = TicketActionsView(_ticket(claimed_by=uuid.uuid4(), status=TicketStatus.CLAIMED))
    ids = _custom_ids(view)
    assert "limerence:ticket:unclaim" in ids
    assert "limerence:ticket:claim" not in ids


def test_actions_view_default_without_ticket_shows_claim() -> None:
    """Registro persistente no boot (sem ticket) cai no padrao historico."""
    view = TicketActionsView()
    assert "limerence:ticket:claim" in _custom_ids(view)


def test_actions_view_always_has_include_remove_close_more() -> None:
    view = TicketActionsView(_ticket())
    ids = _custom_ids(view)
    assert "limerence:ticket:include" in ids
    assert "limerence:ticket:remove_member" in ids
    assert "limerence:ticket:close" in ids
    assert "limerence:ticket:more" in ids


# ============================ export/import ==============================


def test_ticket_settings_export_schema_includes_selection_mode() -> None:
    attrs = {attr for attr, _ in TABLE_SCHEMAS["ticket_settings"]}
    assert "category_selection_mode" in attrs


async def test_import_plan_keeps_current_value_when_field_missing_from_old_export() -> None:
    """Arquivo exportado por uma versao anterior do bot nao tem a chave nova —
    o import nao pode zerar isso pra None (quebraria a coluna NOT NULL)."""
    bot = MagicMock()
    current_settings = MagicMock(category_selection_mode="select", enabled=True)
    bot.config_service.get_ticket_settings = AsyncMock(return_value=current_settings)
    # demais tabelas nao entram neste teste; mocka generico o suficiente pra
    # build_import_plan nao quebrar ao resolver getattr em cada uma.
    bot.config_service.get_settings = AsyncMock(return_value=MagicMock())
    bot.config_service.get_evaluation_settings = AsyncMock(return_value=MagicMock())
    bot.config_service.get_dashboard_settings = AsyncMock(return_value=MagicMock())
    bot.config_service.get_ranking_settings = AsyncMock(return_value=MagicMock())
    bot.config_service.get_anti_spam_settings = AsyncMock(return_value=MagicMock())
    bot.config_service.get_permission_settings = AsyncMock(return_value=MagicMock())
    bot.audit_log_service.get_settings = AsyncMock(return_value=MagicMock())

    guild = MagicMock()
    guild.get_channel = MagicMock(return_value=None)
    guild.get_role = MagicMock(return_value=None)

    old_export = {
        "config_version": 1,
        "ticket_settings": {
            "enabled": True,
            "max_tickets_per_user": None,
            "allow_multiple_tickets": True,
            "auto_close_enabled": True,
            "delete_delay_seconds": 10,
            # sem "category_selection_mode" de proposito — simula export antigo
        },
    }
    for table in TABLE_SCHEMAS:
        old_export.setdefault(table, {})

    plan, changes, _integrity = await build_import_plan(bot, guild, old_export)
    assert plan["ticket_settings"]["category_selection_mode"] == "select"
    mode_change = next(
        c for c in changes if c.table == "ticket_settings" and c.attr == "category_selection_mode"
    )
    assert mode_change.old_value == mode_change.new_value == "select"
