from __future__ import annotations

from database.models.command_help import CommandHelp
from utils.constants import HELP_CATEGORIES
from views.embeds import help_category_embed, help_command_embed, help_main_embed
from views.help_views import HelpCategoryView, HelpMainView


def _command(**overrides: object) -> CommandHelp:
    defaults: dict[str, object] = {
        "command_name": "punir",
        "category": "moderacao",
        "description": "Aplica uma punição.",
        "usage": "/punir usuário tipo motivo",
        "examples": ["/punir @João timeout 30m Spam"],
        "required_permission": "staff",
        "enabled": True,
    }
    defaults.update(overrides)
    return CommandHelp(**defaults)


def test_help_main_embed_has_title() -> None:
    embed = help_main_embed()
    assert "Central de Ajuda" in embed.title


def test_help_category_embed_lists_commands() -> None:
    embed = help_category_embed("moderacao", [_command()])
    assert "/punir" in embed.description


def test_help_category_embed_empty_shows_no_permission_message() -> None:
    embed = help_category_embed("moderacao", [])
    assert "Nenhum comando" in embed.description


def test_help_command_embed_includes_usage_and_examples() -> None:
    embed = help_command_embed(_command())
    assert "/punir usuário tipo motivo" in embed.description
    assert embed.fields[0].value is not None
    assert "/punir @João timeout 30m Spam" in embed.fields[0].value


def test_help_main_view_has_one_button_per_category() -> None:
    view = HelpMainView()
    assert len(view.children) == len(HELP_CATEGORIES)


def test_help_category_view_has_back_button() -> None:
    view = HelpCategoryView()
    assert len(view.children) == 1
