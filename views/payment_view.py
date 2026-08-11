from __future__ import annotations

import base64
import io
from typing import TYPE_CHECKING

import discord

from database.models.payment import PaymentHistory, PaymentStatus
from database.models.plan import Plan
from providers.base import PaymentGatewayError
from providers.manual import ManualProvider
from utils.constants import EMBED_COLOR_DEFAULT, EMBED_COLOR_SUCCESS
from views.base_view import SafeView

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_STATUS_LABELS = {
    PaymentStatus.PENDING: "⏳ Aguardando pagamento",
    PaymentStatus.PROCESSING: "🔄 Processando",
    PaymentStatus.APPROVED: "✅ Confirmado",
    PaymentStatus.REJECTED: "❌ Rejeitado",
    PaymentStatus.EXPIRED: "⌛ Expirado",
    PaymentStatus.CANCELED: "🚫 Cancelado",
    PaymentStatus.REFUNDED: "↩️ Reembolsado",
    PaymentStatus.CHARGEBACK: "⚠️ Chargeback",
}


def _cents_to_display(cents: int, currency: str) -> str:
    return f"{currency} {cents / 100:.2f}"


def payment_embed(payment: PaymentHistory, plan: Plan) -> discord.Embed:
    color = EMBED_COLOR_SUCCESS if payment.status == PaymentStatus.APPROVED else EMBED_COLOR_DEFAULT
    embed = discord.Embed(title=f"💳 Cobrança PIX — {plan.name}", color=color)
    embed.add_field(name="Valor", value=_cents_to_display(payment.amount, payment.currency), inline=True)
    embed.add_field(name="Status", value=_STATUS_LABELS.get(payment.status, payment.status.value), inline=True)
    if payment.expires_at is not None:
        embed.add_field(
            name="Expira em", value=f"<t:{int(payment.expires_at.timestamp())}:R>", inline=True
        )
    if payment.pix_qr_code:
        embed.add_field(name="Código PIX (copia e cola)", value=f"```{payment.pix_qr_code}```", inline=False)
    if payment.pix_qr_code_base64:
        embed.set_image(url="attachment://qrcode.png")
    embed.set_footer(text=f"payment_id={payment.id}")
    return embed


def _qr_code_file(payment: PaymentHistory) -> discord.File | None:
    if not payment.pix_qr_code_base64:
        return None
    try:
        raw = base64.b64decode(payment.pix_qr_code_base64)
    except (ValueError, TypeError):
        return None
    return discord.File(io.BytesIO(raw), filename="qrcode.png")


class PaymentEmbedView(SafeView):
    """Embed de compra pra cobrancas PIX reais (Mercado Pago). Nunca exibe
    token/segredo — so o que o usuario precisa pra pagar."""

    def __init__(self, payment: PaymentHistory, plan: Plan) -> None:
        super().__init__(timeout=None)
        self.payment_id = payment.id
        self.plan_id = plan.id
        self._sync_buttons(payment)

    def _sync_buttons(self, payment: PaymentHistory) -> None:
        final = payment.status not in (PaymentStatus.PENDING, PaymentStatus.PROCESSING)
        self.refresh_button.disabled = final
        self.cancel_button.disabled = final
        self.copy_button.disabled = payment.pix_qr_code is None

    @discord.ui.button(label="📋 Copiar código PIX", style=discord.ButtonStyle.secondary)
    async def copy_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        payment = await bot.payment_service.get(self.payment_id)
        if payment is None or not payment.pix_qr_code:
            await interaction.followup.send("Código PIX indisponível.", ephemeral=True)
            return
        await interaction.followup.send(f"```{payment.pix_qr_code}```", ephemeral=True)

    @discord.ui.button(label="🔄 Atualizar status", style=discord.ButtonStyle.primary)
    async def refresh_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        await interaction.response.defer(ephemeral=True)
        payment = await bot.payment_service.get(self.payment_id)
        if payment is None:
            await interaction.followup.send("Pagamento não encontrado.", ephemeral=True)
            return

        provider = await bot.payment_service.resolve_provider(payment.guild_id)
        if not isinstance(provider, ManualProvider):
            try:
                remote = await provider.get_payment(payment.external_id)
                if remote.status != payment.status:
                    await bot.payment_service.set_status(payment.id, remote.status, provider_payload=dict(remote.raw))
                    if remote.status == PaymentStatus.APPROVED:
                        await bot.subscription_service.confirm_payment(payment.id)
                    payment = await bot.payment_service.get(self.payment_id)
            except PaymentGatewayError:
                await interaction.followup.send("Não foi possível consultar o gateway agora, tente de novo.", ephemeral=True)
                return

        assert payment is not None
        plan = await bot.plan_service.get_plan(self.plan_id)
        if plan is None:
            await interaction.followup.send("Plano não encontrado.", ephemeral=True)
            return
        self._sync_buttons(payment)
        await self._render(interaction, payment, plan)
        await interaction.followup.send(f"Status: {_STATUS_LABELS.get(payment.status, payment.status.value)}", ephemeral=True)

    @discord.ui.button(label="🚫 Cancelar cobrança", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        await interaction.response.defer(ephemeral=True)
        payment = await bot.payment_service.get(self.payment_id)
        if payment is None or payment.status != PaymentStatus.PENDING:
            await interaction.followup.send("Essa cobrança não pode mais ser cancelada.", ephemeral=True)
            return

        provider = await bot.payment_service.resolve_provider(payment.guild_id)
        if not isinstance(provider, ManualProvider):
            try:
                await provider.cancel_payment(payment.external_id)
            except PaymentGatewayError:
                pass
        # expire_payment é idempotente e retorna False sem alterar nada se o
        # pagamento já não estiver mais PENDING (ex.: staff aprovou entre a
        # checagem acima e esta chamada) — nesse caso não reportamos sucesso.
        changed = await bot.subscription_service.expire_payment(payment.id)
        if not changed:
            await interaction.followup.send(
                "Essa cobrança não pode mais ser cancelada (já foi processada).", ephemeral=True
            )
            return

        payment = await bot.payment_service.get(self.payment_id)
        plan = await bot.plan_service.get_plan(self.plan_id)
        if payment is not None and plan is not None:
            self._sync_buttons(payment)
            await self._render(interaction, payment, plan)
        await interaction.followup.send("Cobrança cancelada.", ephemeral=True)

    async def _render(self, interaction: discord.Interaction, payment: PaymentHistory, plan: Plan) -> None:
        embed = payment_embed(payment, plan)
        file = _qr_code_file(payment)
        if interaction.message is None:
            return
        try:
            if file is not None:
                await interaction.message.edit(embed=embed, view=self, attachments=[file])
            else:
                await interaction.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass
