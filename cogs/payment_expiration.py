from __future__ import annotations

from datetime import UTC, datetime

from discord.ext import commands, tasks

from core.bot import LimerenceBot
from core.logger import get_logger
from database.models.payment import PaymentHistory
from providers.base import PaymentGatewayError
from providers.manual import ManualProvider

logger = get_logger("payment_expiration")

_CHECK_INTERVAL_MINUTES = 5


class PaymentExpirationCog(commands.Cog):
    """Expira cobrancas PIX pendentes que passaram do prazo — rede de
    seguranca caso o webhook do gateway se perca (junto com o botao
    'Atualizar status' no embed de compra)."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self.check_expired_payments.start()

    def cog_unload(self) -> None:
        self.check_expired_payments.cancel()

    @tasks.loop(minutes=_CHECK_INTERVAL_MINUTES)
    async def check_expired_payments(self) -> None:
        payments = await self.bot.payment_service.list_pending_expired(before=datetime.now(UTC))
        for payment in payments:
            try:
                await self._expire(payment)
            except Exception:
                logger.exception("Falha ao expirar pagamento %s.", payment.id)

    async def _expire(self, payment: PaymentHistory) -> None:
        provider = await self.bot.payment_service.resolve_provider(payment.guild_id)
        if not isinstance(provider, ManualProvider):
            try:
                await provider.cancel_payment(payment.external_id)
            except PaymentGatewayError:
                logger.warning("Nao foi possivel cancelar pagamento %s no gateway (best-effort).", payment.id)
        await self.bot.subscription_service.expire_payment(payment.id)

    @check_expired_payments.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(PaymentExpirationCog(bot))
