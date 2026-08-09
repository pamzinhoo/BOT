from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from cogs.antispam import AntiSpamCog

_ANTI_SPAM_SETTINGS = SimpleNamespace(
    window_seconds=60,
    cross_channel_threshold=3,
    flood_window_seconds=15,
    flood_threshold=4,
    repeat_threshold=3,
    ignore_staff=True,
    default_action="alerta",
)


_GUILD_SETTINGS = SimpleNamespace(
    blacklist_channel_id=123,
    moderator_role_id=None,
    dev_role_id=None,
    ceo_role_id=None,
    owner_role_id=None,
    support_role_id=None,
)


def _fake_message(*, guild_id: int, author_id: int, content: str, channel_id: int = 1) -> discord.Message:
    message = MagicMock(spec=discord.Message)
    message.author = MagicMock(spec=discord.Member)
    message.author.id = author_id
    message.author.bot = False
    message.author.roles = []
    message.author.guild_permissions = SimpleNamespace(administrator=False)
    message.guild = MagicMock(spec=discord.Guild)
    message.guild.id = guild_id
    message.channel = MagicMock(spec=discord.TextChannel)
    message.channel.id = channel_id
    message.content = content
    message.attachments = []
    message.jump_url = f"https://discord.com/channels/{guild_id}/{channel_id}/999"
    message.created_at = __import__("datetime").datetime.now(__import__("datetime").UTC)
    return message


def _make_cog() -> AntiSpamCog:
    bot = MagicMock()
    bot.config_service.get_settings = AsyncMock(return_value=_GUILD_SETTINGS)
    bot.config_service.get_anti_spam_settings = AsyncMock(return_value=_ANTI_SPAM_SETTINGS)
    cog = AntiSpamCog.__new__(AntiSpamCog)
    cog.bot = bot
    cog._buffers = {}
    cog._last_reported = {}
    return cog


async def test_identical_spam_text_in_different_guilds_uses_separate_buffers() -> None:
    """Auditoria (critico): a assinatura do antispam era so hash do conteudo,
    sem guild_id — texto de spam identico em servidores DIFERENTES caia no
    MESMO buffer, vazando canais/usuarios de um servidor no alerta de outro.
    Corrigido: a chave do buffer agora inclui a guild."""
    cog = _make_cog()
    spam_text = "ganhei nitro gratis clica aqui " * 2  # >= _MIN_TEXT_LENGTH

    message_guild_a = _fake_message(guild_id=111, author_id=1, content=spam_text)
    message_guild_b = _fake_message(guild_id=222, author_id=2, content=spam_text)

    await AntiSpamCog.on_message(cog, message_guild_a)
    await AntiSpamCog.on_message(cog, message_guild_b)

    assert len(cog._buffers) == 2, (
        f"esperava 2 buffers isolados (um por guild), encontrou {len(cog._buffers)} — "
        "ocorrencias de guilds diferentes estao sendo misturadas no mesmo buffer"
    )
    for key in cog._buffers:
        assert key.startswith("111:") or key.startswith("222:"), (
            f"chave do buffer {key!r} nao inclui o guild_id — vazamento cross-guild"
        )


async def test_same_guild_same_text_shares_one_buffer() -> None:
    """Continua funcionando dentro da MESMA guild — nao ficou super-restrito."""
    cog = _make_cog()
    spam_text = "mesmo texto repetido varias vezes " * 2

    message_1 = _fake_message(guild_id=111, author_id=1, content=spam_text, channel_id=10)
    message_2 = _fake_message(guild_id=111, author_id=1, content=spam_text, channel_id=20)

    await AntiSpamCog.on_message(cog, message_1)
    await AntiSpamCog.on_message(cog, message_2)

    assert len(cog._buffers) == 1
    buffer = next(iter(cog._buffers.values()))
    assert len(buffer.occurrences) == 2
