from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from views.pending_punishments_view import _wrong_guild
from views.shop_view import _load_payment_for_guild


def test_wrong_guild_detects_mismatch() -> None:
    interaction = SimpleNamespace(guild_id=111)
    assert _wrong_guild(interaction, 222) is True
    assert _wrong_guild(interaction, 111) is False


async def test_load_payment_for_guild_rejects_payment_from_another_guild() -> None:
    """Auditoria (critico): os botoes de aprovacao manual de pagamento
    (Aprovar/Rejeitar/Pendente/Cancelar) so validavam se quem clicou era
    admin NA GUILD ATUAL — nao que o pagamento referenciado no custom_id
    pertencesse aquela guild. Um admin de uma guild conseguiria manipular o
    pagamento pendente de outra."""
    bot = MagicMock()
    bot.payment_service.get = AsyncMock(return_value=SimpleNamespace(guild_id=999, id="p1"))

    interaction = MagicMock()
    interaction.client = bot
    interaction.guild_id = 111  # pagamento e da guild 999
    interaction.response.send_message = AsyncMock()

    result = await _load_payment_for_guild(interaction, "p1")

    assert result is None
    interaction.response.send_message.assert_awaited_once()
    assert "não encontrado" in interaction.response.send_message.call_args.args[0]


async def test_load_payment_for_guild_accepts_matching_guild() -> None:
    bot = MagicMock()
    payment = SimpleNamespace(guild_id=111, id="p1")
    bot.payment_service.get = AsyncMock(return_value=payment)

    interaction = MagicMock()
    interaction.client = bot
    interaction.guild_id = 111
    interaction.response.send_message = AsyncMock()

    result = await _load_payment_for_guild(interaction, "p1")

    assert result is payment
    interaction.response.send_message.assert_not_called()
