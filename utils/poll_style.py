from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from database.models.poll import PollOption

# Discord so tem 4 estilos REAIS de botao (fora "link") — nao existe cor
# arbitraria/hex, limitacao da propria API, nenhum bot consegue fugir disso.
_BUTTON_STYLE_KEYWORDS: dict[str, str] = {
    "verde": "success",
    "vermelho": "danger",
    "azul": "primary",
    "cinza": "secondary",
}
DEFAULT_BUTTON_STYLE = "secondary"

_DEFAULT_DOTS: dict[str, str] = {
    "success": "🟢",
    "danger": "🔴",
    "primary": "🔵",
    "secondary": "⚪",
}

_DISCORD_BUTTON_STYLES: dict[str, discord.ButtonStyle] = {
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
}


def parse_option_line(raw: str) -> tuple[str, str | None, str]:
    """Analisa 1 linha do textarea de opcoes da enquete no formato
    `Nome | emoji | cor` (emoji e cor sao opcionais — uma linha sem `|`
    continua funcionando como antes, sem emoji, botao cinza). `cor` e uma das
    4 palavras-chave em portugues (verde/vermelho/azul/cinza); qualquer outra
    coisa (ou ausencia) cai no padrao cinza."""
    parts = [p.strip() for p in raw.split("|")]
    name = parts[0]
    emoji = parts[1] if len(parts) > 1 and parts[1] else None
    style_keyword = parts[2].lower() if len(parts) > 2 and parts[2] else ""
    button_style = _BUTTON_STYLE_KEYWORDS.get(style_keyword, DEFAULT_BUTTON_STYLE)
    return name, emoji, button_style


def discord_button_style(button_style: str) -> discord.ButtonStyle:
    return _DISCORD_BUTTON_STYLES.get(button_style, discord.ButtonStyle.secondary)


def option_dot(option: PollOption) -> str:
    """Marcador visual da opcao no embed — emoji custom se configurado,
    senao um circulo colorido combinando com o estilo do botao."""
    if option.emoji:
        return option.emoji
    return _DEFAULT_DOTS.get(option.button_style, "⚪")
