"""Testes da nova funcionalidade: avaliacao de ticket configuravel entre
Ticket / DM / Ticket+DM (EvaluationSettings.evaluation_method).

Cobre: normalizacao do metodo, placeholders novos em render_placeholders,
embeds/textos de avaliacao (defaults + personalizados), custom_id estavel do
botao de avaliacao por DM (sobrevive a restart via DynamicItem), o fluxo de
fechamento (`TicketActionsView.close`) respeitando os 3 modos, DM bloqueada
nao quebrando o fechamento, prevencao de avaliacao duplicada (reaproveitada
do sistema existente), e export/import da configuracao nova."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import discord

from database.models.evaluation_settings import (
    DEFAULT_EVALUATION_METHOD,
    EVALUATION_METHODS,
    EvaluationSettings,
)
from database.models.ticket import Ticket, TicketCategory, TicketStatus
from database.models.ticket_panel import TicketPanel
from services.config_transfer_service import TABLE_SCHEMAS, build_import_plan
from services.evaluation_service import normalize_evaluation_method
from services.plan_service import render_placeholders
from views.dm_evaluation_view import DMRatingButton
from views.embeds import (
    DEFAULT_EVALUATION_DM_BUTTON_LABEL,
    DEFAULT_EVALUATION_DM_TITLE,
    DEFAULT_EVALUATION_THANKS_MESSAGE,
    evaluation_button_label,
    evaluation_dm_embed,
    evaluation_thanks_message,
    ticket_closed_summary_embed,
)
from views.ticket_actions_view import TicketActionsView


def _ticket(*, closed: bool = True) -> Ticket:
    ticket = Ticket(
        guild_id=1,
        channel_id=999,
        opened_by_discord_id=42,
        category=TicketCategory.OUTRO,
        status=TicketStatus.CLOSED if closed else TicketStatus.CLAIMED,
        claimed_by_staff_id=uuid.uuid4(),
        created_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        closed_at=datetime(2026, 8, 16, 18, 0, tzinfo=UTC) if closed else None,
        closed_by_discord_id=777 if closed else None,
    )
    ticket.id = uuid.uuid4()
    return ticket


def _eval_settings(**overrides: object) -> EvaluationSettings:
    settings = EvaluationSettings(guild_id=1, enabled=True)
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def _panel() -> TicketPanel:
    panel = TicketPanel(guild_id=1, key="suporte", name="Suporte")
    panel.id = uuid.uuid4()
    return panel


def _opener() -> MagicMock:
    opener = MagicMock(spec=discord.Member)
    opener.mention = "<@42>"
    opener.display_name = "ClienteFicticio"
    return opener


def _guild(name: str = "ServidorFicticio") -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.name = name
    guild.id = 1
    return guild


# ============================ normalizacao do metodo ==============================


def test_normalize_evaluation_method_defaults_unknown_to_ticket() -> None:
    assert normalize_evaluation_method(None) == DEFAULT_EVALUATION_METHOD
    assert normalize_evaluation_method("") == "ticket"
    assert normalize_evaluation_method("qualquer-coisa-invalida") == "ticket"
    assert normalize_evaluation_method("dm") == "dm"
    assert normalize_evaluation_method("both") == "both"


def test_evaluation_methods_has_exactly_three_options() -> None:
    assert set(EVALUATION_METHODS) == {"ticket", "dm", "both"}


def test_evaluation_settings_model_default_is_ticket() -> None:
    """Guild nova (get_or_create) cai no comportamento historico."""
    settings = EvaluationSettings(guild_id=999)
    assert settings.__table__.columns["evaluation_method"].default.arg == "ticket"


# ============================ placeholders ==============================


def test_render_placeholders_substitutes_ticket_evaluation_fields() -> None:
    guild = _guild("High City")  # nome fictício só pra provar substituição real
    opener = _opener()
    template = (
        "{server}/{guild} - {ticket_type}/{category} - {claimed_by} - {closed_by} - "
        "{opened_at} - {closed_at} - {ticket_id} - {reason} - {user}"
    )
    result = render_placeholders(
        template,
        member=opener,
        guild=guild,
        ticket_type="Suporte",
        claimed_by="StaffFicticio",
        closed_by="StaffFicticio",
        opened_at="16/08/2026 10:00",
        closed_at="16/08/2026 18:00",
        ticket_id="e788abcd",
        reason=None,
    )
    assert "High City" in result
    assert "Suporte" in result
    assert "StaffFicticio" in result
    assert "e788abcd" in result
    assert "—" in result  # reason=None vira "—"
    assert opener.mention in result


def test_render_placeholders_without_ticket_context_falls_back_to_dash() -> None:
    result = render_placeholders("{ticket_type}|{claimed_by}|{reason}")
    assert result == "—|—|—"


# ============================ embeds/textos ==============================


def test_evaluation_dm_embed_uses_defaults_when_not_customized() -> None:
    settings = _eval_settings()  # sem dm_* customizado
    embed = evaluation_dm_embed(
        settings,
        guild=_guild(),
        ticket=_ticket(),
        panel=None,
        opener=_opener(),
        claimed_by_name="StaffFicticio",
        closed_by_name="StaffFicticio",
    )
    assert embed.title == DEFAULT_EVALUATION_DM_TITLE
    assert DEFAULT_EVALUATION_DM_BUTTON_LABEL in embed.description
    assert "ServidorFicticio" in embed.description
    assert "StaffFicticio" in embed.description


def test_evaluation_dm_embed_uses_custom_texts_and_real_data_never_fixtures() -> None:
    settings = _eval_settings(
        dm_embed_title="Título customizado — {ticket_type}",
        dm_embed_description="Descrição customizada.",
        dm_prompt_text="Prompt customizado.",
        dm_button_label="Clique pra avaliar",
    )
    ticket = _ticket()
    panel = _panel()
    embed = evaluation_dm_embed(
        settings,
        guild=_guild("OutroServidor"),
        ticket=ticket,
        panel=panel,
        opener=_opener(),
        claimed_by_name="Fulano",
        closed_by_name="Beltrano",
    )
    assert embed.title == "Título customizado — Suporte"  # placeholder resolvido, nao fixo
    assert "Descrição customizada." in embed.description
    assert "Prompt customizado." in embed.description
    assert "Clique pra avaliar" in embed.description
    assert "OutroServidor" in embed.description
    assert "Fulano" in embed.description
    assert "Beltrano" in embed.description
    assert str(ticket.id)[:8] in embed.description
    # nenhum valor fictício do exemplo da especificação vaza pro embed real
    assert "High City" not in embed.description
    assert "Nala" not in embed.description


def test_evaluation_button_label_falls_back_to_default() -> None:
    assert evaluation_button_label(_eval_settings()) == DEFAULT_EVALUATION_DM_BUTTON_LABEL
    assert evaluation_button_label(_eval_settings(dm_button_label="Avaliar agora")) == "Avaliar agora"


def test_evaluation_thanks_message_uses_default_and_custom() -> None:
    assert evaluation_thanks_message(_eval_settings()) == DEFAULT_EVALUATION_THANKS_MESSAGE
    custom = _eval_settings(dm_thanks_message="Valeu, {user}!")
    rendered = evaluation_thanks_message(custom, member=_opener(), guild=_guild())
    assert rendered == "Valeu, <@42>!"


def test_ticket_closed_summary_embed_has_real_fields_no_fixed_values() -> None:
    ticket = _ticket()
    embed = ticket_closed_summary_embed(
        guild=_guild("ServidorReal"),
        ticket=ticket,
        panel=None,
        closed_by_mention="<@777>",
        closed_by_name="QuemFechou",
        claimed_by_name="QuemAssumiu",
    )
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Servidor"] == "ServidorReal"
    assert fields["Assumido por"] == "QuemAssumiu"
    assert fields["Fechado por"] == "QuemFechou"
    assert fields["ID do ticket"] == f"`{str(ticket.id)[:8]}`"
    assert fields["Motivo"] == "—"
    assert "High City" not in embed.description
    assert "resolvido" not in fields["Motivo"]


# ============================ custom_id estavel (restart) ==============================


def test_dm_rating_button_custom_id_is_stable_and_embeds_ticket_and_rating() -> None:
    ticket_id = uuid.uuid4()
    button = DMRatingButton(ticket_id, 4)
    assert button.item.custom_id == f"limerence:eval_dm:{ticket_id}:4"


def test_dm_rating_button_custom_id_matches_registered_template() -> None:
    ticket_id = uuid.uuid4()
    button = DMRatingButton(ticket_id, 5)
    match = re.fullmatch(DMRatingButton.__discord_ui_compiled_template__, button.item.custom_id)
    assert match is not None
    assert match["ticket_id"] == str(ticket_id)
    assert match["rating"] == "5"


async def test_dm_rating_button_from_custom_id_reconstructs_after_restart() -> None:
    """Simula o que o discord.py faz ao receber um clique depois de um
    restart: so tem o custom_id salvo na mensagem, precisa reconstruir o
    item do zero a partir dele."""
    ticket_id = uuid.uuid4()
    custom_id = f"limerence:eval_dm:{ticket_id}:3"
    match = re.fullmatch(DMRatingButton.__discord_ui_compiled_template__, custom_id)
    assert match is not None
    rebuilt = await DMRatingButton.from_custom_id(MagicMock(), MagicMock(), match)
    assert rebuilt.ticket_id == ticket_id
    assert rebuilt.rating == 3


# ============================ export/import ==============================


def test_evaluation_settings_export_schema_includes_new_fields() -> None:
    attrs = {attr for attr, _ in TABLE_SCHEMAS["evaluation_settings"]}
    assert {
        "evaluation_method",
        "dm_embed_title",
        "dm_embed_description",
        "dm_prompt_text",
        "dm_button_label",
        "dm_thanks_message",
    } <= attrs


async def test_import_plan_keeps_current_evaluation_method_when_missing_from_old_export() -> None:
    bot = MagicMock()
    current = MagicMock(evaluation_method="both", enabled=True)
    bot.config_service.get_evaluation_settings = AsyncMock(return_value=current)
    bot.config_service.get_settings = AsyncMock(return_value=MagicMock())
    bot.config_service.get_ticket_settings = AsyncMock(return_value=MagicMock())
    bot.config_service.get_dashboard_settings = AsyncMock(return_value=MagicMock())
    bot.config_service.get_ranking_settings = AsyncMock(return_value=MagicMock())
    bot.config_service.get_anti_spam_settings = AsyncMock(return_value=MagicMock())
    bot.config_service.get_permission_settings = AsyncMock(return_value=MagicMock())
    bot.audit_log_service.get_settings = AsyncMock(return_value=MagicMock())

    guild = MagicMock()
    guild.get_channel = MagicMock(return_value=None)
    guild.get_role = MagicMock(return_value=None)

    old_export: dict = {
        "config_version": 1,
        "evaluation_settings": {
            "enabled": True,
            "min_comment_rating": 2,
            "star_emoji": "⭐",
            # sem evaluation_method/dm_* — simula export de versao anterior
        },
    }
    for table in TABLE_SCHEMAS:
        old_export.setdefault(table, {})

    plan, changes, _integrity = await build_import_plan(bot, guild, old_export)
    assert plan["evaluation_settings"]["evaluation_method"] == "both"
    change = next(
        c for c in changes if c.table == "evaluation_settings" and c.attr == "evaluation_method"
    )
    assert change.old_value == change.new_value == "both"


# ============================ fluxo de fechamento (3 modos) ==============================


class _Blocked(discord.HTTPException):
    """DM bloqueada — nao usa o __init__ real do HTTPException (que exige
    response/message reais), so precisa ser um discord.HTTPException valido
    pro `except discord.HTTPException` capturar."""

    def __init__(self) -> None:  # noqa: super-init-not-called
        pass


def _closer() -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.guild_permissions.administrator = True
    member.id = 777
    member.mention = "<@777>"
    member.display_name = "QuemFechou"
    return member


def _build_close_bot(*, evaluation_method: str, opener_send: AsyncMock | None = None) -> MagicMock:
    bot = MagicMock()
    ticket = _ticket(closed=False)
    closed_ticket = _ticket(closed=True)
    closed_ticket.id = ticket.id

    bot.ticket_service.get_by_channel_id = AsyncMock(return_value=ticket)
    staff = MagicMock()
    staff.display_name = "QuemAssumiu"
    bot.staff_service.get_by_id = AsyncMock(return_value=staff)
    bot.ticket_panel_service.get_panel_for_ticket = AsyncMock(return_value=None)

    close_result = MagicMock()
    close_result.ticket = closed_ticket
    close_result.unlocked_achievements = []
    bot.ticket_service.close_ticket = AsyncMock(return_value=close_result)

    bot.log_service.record_background = MagicMock()
    bot.painel_service.refresh_dashboard = AsyncMock()

    behaviour = MagicMock()
    behaviour.evaluation_enabled = True
    bot.ticket_panel_service.behaviour_for_ticket = AsyncMock(return_value=behaviour)

    eval_settings = _eval_settings(evaluation_method=evaluation_method)
    bot.config_service.get_evaluation_settings = AsyncMock(return_value=eval_settings)

    return bot, ticket, closed_ticket, opener_send


def _close_interaction(bot: MagicMock, *, opener_member: MagicMock | None) -> MagicMock:
    interaction = MagicMock()
    interaction.client = bot
    interaction.user = _closer()
    interaction.channel_id = 999
    guild = _guild()
    guild.get_member = MagicMock(return_value=opener_member)
    guild.get_channel = MagicMock(return_value=None)
    interaction.guild = guild
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    interaction.channel = channel
    message = MagicMock(spec=discord.Message)
    message.edit = AsyncMock()
    interaction.message = message
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


async def test_close_ticket_only_sends_channel_prompt_not_dm(monkeypatch) -> None:
    opener = _opener()
    opener.send = AsyncMock()
    bot, ticket, closed_ticket, _ = _build_close_bot(evaluation_method="ticket")

    confirm = MagicMock(confirmed=True)
    confirm.wait = AsyncMock()
    monkeypatch.setattr("views.ticket_actions_view.ConfirmCloseView", lambda closer_id: confirm)

    interaction = _close_interaction(bot, opener_member=opener)
    view = TicketActionsView(ticket)
    await view.close.callback(interaction)

    # 1 chamada de channel.send pro resumo do fechamento + 1 pro prompt de avaliacao
    assert interaction.channel.send.await_count == 2
    opener.send.assert_not_awaited()


async def test_close_dm_only_sends_dm_not_channel_prompt(monkeypatch) -> None:
    opener = _opener()
    opener.send = AsyncMock()
    bot, ticket, closed_ticket, _ = _build_close_bot(evaluation_method="dm")

    confirm = MagicMock(confirmed=True)
    confirm.wait = AsyncMock()
    monkeypatch.setattr("views.ticket_actions_view.ConfirmCloseView", lambda closer_id: confirm)

    interaction = _close_interaction(bot, opener_member=opener)
    view = TicketActionsView(ticket)
    await view.close.callback(interaction)

    # so 1 chamada de channel.send (o resumo do fechamento, sem prompt de avaliacao)
    assert interaction.channel.send.await_count == 1
    opener.send.assert_awaited_once()


async def test_close_both_sends_channel_prompt_and_dm(monkeypatch) -> None:
    opener = _opener()
    opener.send = AsyncMock()
    bot, ticket, closed_ticket, _ = _build_close_bot(evaluation_method="both")

    confirm = MagicMock(confirmed=True)
    confirm.wait = AsyncMock()
    monkeypatch.setattr("views.ticket_actions_view.ConfirmCloseView", lambda closer_id: confirm)

    interaction = _close_interaction(bot, opener_member=opener)
    view = TicketActionsView(ticket)
    await view.close.callback(interaction)

    assert interaction.channel.send.await_count == 2
    opener.send.assert_awaited_once()


async def test_close_dm_blocked_does_not_break_closing(monkeypatch) -> None:
    """Usuario bloqueou DM — o ticket continua fechado normalmente, sem
    exception propagando e sem a mensagem de fechamento no canal ser afetada."""
    opener = _opener()
    opener.send = AsyncMock(side_effect=_Blocked())
    bot, ticket, closed_ticket, _ = _build_close_bot(evaluation_method="dm")

    confirm = MagicMock(confirmed=True)
    confirm.wait = AsyncMock()
    monkeypatch.setattr("views.ticket_actions_view.ConfirmCloseView", lambda closer_id: confirm)

    interaction = _close_interaction(bot, opener_member=opener)
    view = TicketActionsView(ticket)
    await view.close.callback(interaction)  # nao pode levantar excecao

    opener.send.assert_awaited_once()
    # a mensagem de fechamento no canal ainda foi enviada normalmente
    assert interaction.channel.send.await_count == 1
    bot.ticket_service.close_ticket.assert_awaited_once()


async def test_close_dm_only_skips_dm_gracefully_when_opener_left_guild(monkeypatch) -> None:
    """opener nao encontrado (saiu do servidor e nao pode ser resolvido por
    fetch_user) — nao quebra o fechamento, so nao manda a DM."""
    bot, ticket, closed_ticket, _ = _build_close_bot(evaluation_method="dm")
    bot.fetch_user = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=404), "not found"))

    confirm = MagicMock(confirmed=True)
    confirm.wait = AsyncMock()
    monkeypatch.setattr("views.ticket_actions_view.ConfirmCloseView", lambda closer_id: confirm)

    interaction = _close_interaction(bot, opener_member=None)
    view = TicketActionsView(ticket)
    await view.close.callback(interaction)  # nao pode levantar excecao

    assert interaction.channel.send.await_count == 1
