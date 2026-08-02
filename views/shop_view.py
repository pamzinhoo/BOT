from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, Any

import discord
from views.base_view import SafeView

from core.logger import get_logger
from database.models.payment import PaymentHistory
from database.models.plan import Plan
from database.models.subscription import BillingCycle
from providers.manual import ManualProvider
from services.coupon_service import CouponError
from services.subscription_service import DuplicateSubscriptionError, MissingPriceError
from utils.checks import member_is_admin
from utils.constants import EMBED_COLOR_WARNING

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("shop_view")

_CYCLE_LABELS = {
    BillingCycle.MONTHLY: "Mensal",
    BillingCycle.YEARLY: "Anual",
    BillingCycle.ONE_TIME: "Pagamento único",
}


def _cents_to_display(cents: int, currency: str) -> str:
    return f"{currency} {cents / 100:.2f}"


def _available_cycles(plan: Plan) -> list[BillingCycle]:
    cycles = []
    if plan.price_monthly is not None:
        cycles.append(BillingCycle.MONTHLY)
    if plan.price_yearly is not None:
        cycles.append(BillingCycle.YEARLY)
    if plan.price_one_time is not None:
        cycles.append(BillingCycle.ONE_TIME)
    return cycles


def _price_for(plan: Plan, cycle: BillingCycle) -> int | None:
    return {
        BillingCycle.MONTHLY: plan.price_monthly,
        BillingCycle.YEARLY: plan.price_yearly,
        BillingCycle.ONE_TIME: plan.price_one_time,
    }[cycle]


def plan_card_embed(plan: Plan, benefits: list[str], *, position: int, total: int) -> discord.Embed:
    color = discord.Color(plan.color) if plan.color is not None else EMBED_COLOR_WARNING
    title = f"{plan.emoji or ''} {plan.name}".strip()
    if plan.is_recommended:
        title += "  ⭐ Mais Popular"
    embed = discord.Embed(title=title, description=plan.description or None, color=color)

    for cycle in _available_cycles(plan):
        price = _price_for(plan, cycle)
        assert price is not None
        embed.add_field(name=_CYCLE_LABELS[cycle], value=_cents_to_display(price, plan.currency), inline=True)

    if benefits:
        embed.add_field(
            name="Benefícios",
            value="\n".join(f"✔ {text}" for text in benefits),
            inline=False,
        )
    embed.set_footer(text=f"Plano {position + 1}/{total}")
    return embed


def shop_panel_embed(plans: list[Plan]) -> discord.Embed:
    embed = discord.Embed(
        title="🛒 Loja",
        description="Clique no botão abaixo pra ver os planos disponíveis e comprar.",
        color=EMBED_COLOR_WARNING,
    )
    if not plans:
        embed.description = "Nenhum plano disponível no momento."
        return embed
    for plan in plans:
        cycles = _available_cycles(plan)
        prices = " · ".join(
            f"{_CYCLE_LABELS[c]}: {_cents_to_display(_price_for(plan, c), plan.currency)}" for c in cycles
        )
        name = f"{plan.emoji or ''} {plan.name}".strip()
        if plan.is_recommended:
            name += " ⭐"
        embed.add_field(name=name, value=prices or "—", inline=False)
    embed.set_footer(text="Atualizado automaticamente quando a staff altera os planos.")
    return embed


class ShopPanelView(SafeView):
    """Painel fixo da loja — postado uma vez num canal (via /loja publicar:True
    ou ao definir o Canal da Loja em /config painel > Monetização) e atualizado
    sozinho quando os planos mudam. So tem um botao publico com custom_id fixo;
    a navegacao/compra de verdade acontece na ShopView efemera de sempre, cada
    clique gera uma instancia nova — sem estado (index) compartilhado entre
    usuarios diferentes."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🛒 Ver planos", style=discord.ButtonStyle.success, custom_id="limerence:shop:open"
    )
    async def open_shop(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
        assert interaction.guild_id is not None
        plans = await bot.plan_service.list_plans(interaction.guild_id, only_active=True)
        if not plans:
            await interaction.response.send_message("Nenhum plano disponível no momento.", ephemeral=True)
            return
        benefits_by_plan = {}
        for plan in plans:
            benefits = await bot.plan_service.list_benefits(plan.id)
            benefits_by_plan[plan.id] = [b.text for b in benefits]
        view = ShopView(plans, benefits_by_plan)
        await interaction.response.send_message(embed=view.render_embed(), view=view, ephemeral=True)


class ShopView(SafeView):
    """/loja — navega pelos planos ativos da guild e inicia a compra. So
    exibe o que o admin cadastrou: sem plano fixo, sem beneficio fixo."""

    def __init__(
        self,
        plans: list[Plan],
        benefits_by_plan: dict[uuid.UUID, list[str]],
        index: int = 0,
        *,
        member: discord.Member | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self.plans = plans
        self.benefits_by_plan = benefits_by_plan
        self.index = index
        # so vem preenchido quando a Loja e aberta de fora de um servidor
        # (ex.: botao da DM de renovacao), onde interaction.user e um User
        self.member = member
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.prev_button.disabled = self.index <= 0
        self.next_button.disabled = self.index >= len(self.plans) - 1
        self.buy_button.disabled = not _available_cycles(self.plans[self.index])

    @property
    def current_plan(self) -> Plan:
        return self.plans[self.index]

    def render_embed(self) -> discord.Embed:
        plan = self.current_plan
        return plan_card_embed(
            plan, self.benefits_by_plan.get(plan.id, []), position=self.index, total=len(self.plans)
        )

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.index = max(0, self.index - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.render_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.index = min(len(self.plans) - 1, self.index + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.render_embed(), view=self)

    @discord.ui.button(label="🛒 Comprar", style=discord.ButtonStyle.success)
    async def buy_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        plan = self.current_plan
        cycles = _available_cycles(plan)
        if len(cycles) == 1:
            await _start_purchase(interaction, plan, cycles[0], member=self.member)
            return
        view = SafeView(timeout=120)
        view.add_item(_CycleSelect(plan, cycles, member=self.member))
        await interaction.response.send_message(
            f"Escolha a forma de cobrança para **{plan.name}**:", view=view, ephemeral=True
        )

    @discord.ui.button(label="📜 Ver Benefícios", style=discord.ButtonStyle.secondary)
    async def benefits_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        plan = self.current_plan
        benefits = self.benefits_by_plan.get(plan.id, [])
        text = "\n".join(f"✔ {b}" for b in benefits) if benefits else "Nenhum benefício cadastrado."
        await interaction.response.send_message(
            f"**Benefícios — {plan.name}**\n{text}", ephemeral=True
        )


class _CycleSelect(discord.ui.Select[Any]):
    def __init__(
        self, plan: Plan, cycles: list[BillingCycle], *, member: discord.Member | None = None
    ) -> None:
        options = [
            discord.SelectOption(
                label=f"{_CYCLE_LABELS[cycle]} — {_cents_to_display(_price_for(plan, cycle), plan.currency)}",
                value=cycle.value,
            )
            for cycle in cycles
        ]
        super().__init__(placeholder="Ciclo de cobrança...", options=options, min_values=1, max_values=1)
        self.plan = plan
        self.member = member

    async def callback(self, interaction: discord.Interaction) -> None:
        await _start_purchase(
            interaction, self.plan, BillingCycle(self.values[0]), member=self.member
        )


async def _start_purchase(
    interaction: discord.Interaction,
    plan: Plan,
    cycle: BillingCycle,
    *,
    member: discord.Member | None = None,
    renewal: bool = False,
    coupon_code: str | None = None,
    skip_coupon_prompt: bool = False,
    payer_information: str | None = None,
    skip_payer_prompt: bool = False,
) -> None:
    """Fluxo unico de compra (Loja, botao Renovar, etc.).

    A etapa de cupom e OPCIONAL e nao-bloqueante: se a guild nao tiver nenhum
    cupom ativo, nada muda em relacao ao comportamento historico. Se tiver, o
    comprador ve uma tela "Possui um cupom?" onde pode simplesmente seguir sem
    cupom. Nenhuma cobranca e gerada antes do cupom ser validado.

    A etapa de "quem vai pagar" (Modal) so aparece quando o provider resolvido
    pra guild e o ManualProvider (PIX manual) — gateways automaticos tem seu
    proprio checkout, ninguem precisa identificar quem fez o PIX."""
    bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
    member = member if member is not None else interaction.user  # type: ignore[assignment]
    if not isinstance(member, discord.Member):
        return

    if coupon_code is None and not skip_coupon_prompt and not interaction.response.is_done():
        coupons = await bot.coupon_service.list_coupons(member.guild.id, only_active=True)
        if coupons:
            price = _price_for(plan, cycle)
            await interaction.response.send_message(
                f"Você possui um cupom de desconto para **{plan.name}**"
                + (f" ({_cents_to_display(price, plan.currency)})?" if price is not None else "?"),
                view=_CouponPromptView(plan, cycle, member=member, renewal=renewal),
                ephemeral=True,
            )
            return

    if payer_information is None and not skip_payer_prompt and not interaction.response.is_done():
        provider = await bot.payment_service.resolve_provider(member.guild.id)
        if isinstance(provider, ManualProvider):
            await interaction.response.send_modal(
                _PayerInfoModal(plan, cycle, member=member, renewal=renewal, coupon_code=coupon_code)
            )
            return

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=interaction.guild is not None)

    try:
        subscription, payment, result = await bot.subscription_service.start_purchase(
            member, plan, cycle, renewal=renewal, coupon_code=coupon_code,
            payer_information=payer_information,
        )
    except (DuplicateSubscriptionError, MissingPriceError, CouponError) as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return

    content = None
    if coupon_code:
        original = _price_for(plan, cycle)
        if original is not None:
            content = (
                f"🎟️ Cupom **{coupon_code.strip().upper()}** aplicado — "
                f"de ~~{_cents_to_display(original, plan.currency)}~~ por "
                f"**{_cents_to_display(payment.amount, payment.currency)}**."
            )

    if result.qr_code or result.qr_code_base64:
        from views.payment_view import PaymentEmbedView, _qr_code_file, payment_embed

        view = PaymentEmbedView(payment, plan)
        embed = payment_embed(payment, plan)
        file = _qr_code_file(payment)
        if file is not None:
            await interaction.followup.send(
                content=content, embed=embed, view=view, file=file, ephemeral=True
            )
        else:
            await interaction.followup.send(content=content, embed=embed, view=view, ephemeral=True)
    else:
        await interaction.followup.send(
            (f"{content}\n" if content else "")
            + "✅ Pedido registrado! Assim que o pagamento for confirmado pela equipe, "
            "seu cargo e benefícios serão liberados automaticamente.",
            ephemeral=True,
        )

    # notifica a staff sempre que for ManualProvider — com ou sem QR, alguem
    # precisa aprovar manualmente. Gateways automaticos (MercadoPago) nao
    # passam por aqui: a confirmacao deles vem de webhook/consulta de status.
    if payment.provider == "manual":
        await _notify_approval_channel(bot, member, plan, cycle, payment, result.checkout_url)


# alias publico: qualquer outra tela (ex.: botao "Renovar" das mensagens de
# renovacao) reaproveita ESTE fluxo em vez de recriar cobranca/checkout.
start_purchase_flow = _start_purchase


class _CouponPromptView(SafeView):
    """Passo intermediario entre escolher plano/ciclo e gerar a cobranca. Da
    pra pular direto ("Continuar sem cupom") — ninguem e obrigado a passar por
    aqui."""

    def __init__(
        self,
        plan: Plan,
        cycle: BillingCycle,
        *,
        member: discord.Member,
        renewal: bool,
    ) -> None:
        super().__init__(timeout=180)
        self.plan = plan
        self.cycle = cycle
        self.member = member
        self.renewal = renewal

    @discord.ui.button(label="🎟️ Tenho um cupom", style=discord.ButtonStyle.primary)
    async def with_coupon(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            _CouponCodeModal(self.plan, self.cycle, member=self.member, renewal=self.renewal)
        )

    @discord.ui.button(label="Continuar sem cupom", style=discord.ButtonStyle.secondary)
    async def without_coupon(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await _start_purchase(
            interaction,
            self.plan,
            self.cycle,
            member=self.member,
            renewal=self.renewal,
            skip_coupon_prompt=True,
        )


class _PayerInfoModal(discord.ui.Modal, title="Quem vai pagar?"):
    """Passo obrigatorio antes de gerar o PIX manual — identifica pra staff
    quem vai aparecer no extrato bancario (nem sempre e a mesma pessoa da
    conta Discord). Texto salvo integralmente em payment_history.payer_information,
    nunca resumido/editado pelo bot."""

    payer_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Quem fará o pagamento?",
        style=discord.TextStyle.paragraph,
        placeholder="Ex.: Minha mãe fará o PIX.\nNome dela no banco é Júlia.",
        max_length=500,
        required=True,
    )

    def __init__(
        self,
        plan: Plan,
        cycle: BillingCycle,
        *,
        member: discord.Member,
        renewal: bool,
        coupon_code: str | None = None,
    ) -> None:
        super().__init__()
        self.plan = plan
        self.cycle = cycle
        self.member = member
        self.renewal = renewal
        self.coupon_code = coupon_code

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await _start_purchase(
            interaction,
            self.plan,
            self.cycle,
            member=self.member,
            renewal=self.renewal,
            coupon_code=self.coupon_code,
            payer_information=str(self.payer_input.value),
            skip_coupon_prompt=True,
            skip_payer_prompt=True,
        )


class _CouponCodeModal(discord.ui.Modal, title="Cupom de desconto"):
    code_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Código do cupom", placeholder="Ex: PROMO10", max_length=64
    )

    def __init__(
        self,
        plan: Plan,
        cycle: BillingCycle,
        *,
        member: discord.Member,
        renewal: bool,
    ) -> None:
        super().__init__()
        self.plan = plan
        self.cycle = cycle
        self.member = member
        self.renewal = renewal

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
        original = _price_for(self.plan, self.cycle)
        if original is None:
            await interaction.response.send_message(
                "Este plano não tem preço configurado para esse ciclo de cobrança.", ephemeral=True
            )
            return

        code = str(self.code_input.value)
        try:
            application = await bot.coupon_service.validate_and_price(
                self.member.guild.id, code, self.member, self.plan, self.cycle, original
            )
        except CouponError as exc:
            # erro preciso do servico + chance de tentar outro codigo/seguir sem
            await interaction.response.send_message(
                f"❌ {exc}",
                view=_CouponPromptView(
                    self.plan, self.cycle, member=self.member, renewal=self.renewal
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🎟️ Cupom aplicado",
            description=f"Cupom **{application.coupon.code}** válido para **{self.plan.name}**.",
            color=EMBED_COLOR_WARNING,
        )
        embed.add_field(
            name="Valor original",
            value=_cents_to_display(application.original_amount, self.plan.currency),
        )
        embed.add_field(
            name="Desconto",
            value=f"- {_cents_to_display(application.discount_amount, self.plan.currency)}",
        )
        embed.add_field(
            name="Valor final",
            value=f"**{_cents_to_display(application.final_amount, self.plan.currency)}**",
        )
        embed.set_footer(text="Confirme para gerar a cobrança com o desconto aplicado.")
        await interaction.response.send_message(
            embed=embed,
            view=_ConfirmCouponPurchaseView(
                self.plan,
                self.cycle,
                member=self.member,
                renewal=self.renewal,
                code=application.coupon.code,
            ),
            ephemeral=True,
        )


class _ConfirmCouponPurchaseView(SafeView):
    """A cobranca so e criada depois deste clique — o comprador ve preco
    original, desconto e preco final antes de qualquer PIX ser gerado."""

    def __init__(
        self,
        plan: Plan,
        cycle: BillingCycle,
        *,
        member: discord.Member,
        renewal: bool,
        code: str,
    ) -> None:
        super().__init__(timeout=180)
        self.plan = plan
        self.cycle = cycle
        self.member = member
        self.renewal = renewal
        self.code = code

    @discord.ui.button(label="✅ Confirmar compra", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await _start_purchase(
            interaction,
            self.plan,
            self.cycle,
            member=self.member,
            renewal=self.renewal,
            coupon_code=self.code,
            skip_coupon_prompt=True,
        )

    @discord.ui.button(label="Trocar cupom", style=discord.ButtonStyle.secondary)
    async def change(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            _CouponCodeModal(self.plan, self.cycle, member=self.member, renewal=self.renewal)
        )


async def _notify_approval_channel(
    bot: "LimerenceBot",
    member: discord.Member,
    plan: Plan,
    cycle: BillingCycle,
    payment: PaymentHistory,
    checkout_url: str | None,
) -> None:
    settings = await bot.subscription_service.get_settings(member.guild.id)
    if settings.approval_channel_id is None:
        return
    channel = member.guild.get_channel(settings.approval_channel_id)
    if not isinstance(channel, discord.abc.Messageable):
        return

    # numero curto de exibicao — nao e sequencial, so um jeito legivel de
    # citar o pedido sem colar o UUID inteiro (que fica no footer/comando).
    order_number = str(payment.id).split("-")[0].upper()
    embed = discord.Embed(
        title=f"💰 Pedido #{order_number}",
        description=f"{member.mention} quer assinar **{plan.name}**.",
        color=discord.Color(plan.color) if plan.color is not None else EMBED_COLOR_WARNING,
    )
    embed.add_field(name="Ciclo", value=_CYCLE_LABELS[cycle])
    embed.add_field(name="Valor", value=_cents_to_display(payment.amount, payment.currency))
    embed.add_field(name="Data", value=f"<t:{int(payment.created_at.timestamp())}:f>", inline=False)
    if payment.payer_information:
        # visualizacao truncada no embed (limite de 1024 do Discord) — o
        # texto completo continua salvo integralmente em payment_history.
        embed.add_field(
            name="Informações do Pagador", value=payment.payer_information[:1024], inline=False
        )
    if payment.pix_qr_code:
        embed.add_field(name="Código PIX (copia e cola)", value=f"```{payment.pix_qr_code}```", inline=False)
    if checkout_url:
        embed.add_field(name="Checkout", value=checkout_url, inline=False)
    embed.set_footer(text=f"payment_id={payment.id}")

    file = None
    if payment.pix_qr_code_base64:
        from views.payment_view import _qr_code_file

        file = _qr_code_file(payment)
        if file is not None:
            embed.set_image(url="attachment://qrcode.png")

    try:
        if file is not None:
            await channel.send(embed=embed, view=purchase_approval_view(payment.id), file=file)
        else:
            await channel.send(embed=embed, view=purchase_approval_view(payment.id))
    except discord.HTTPException:
        pass


async def _deny_if_not_admin(interaction: discord.Interaction) -> bool:
    if not await member_is_admin(interaction):
        await interaction.response.send_message(
            "Apenas admins podem gerenciar pagamentos.", ephemeral=True
        )
        return True
    return False


async def _disable_and_edit(interaction: discord.Interaction) -> None:
    """So atualiza a mensagem (botoes desabilitados) — nunca deve derrubar a
    acao que ja foi executada com sucesso no banco. Qualquer falha aqui
    (parsing do custom_id, erro da API) so vira um log, a interacao ja
    recebe a confirmacao de sucesso do followup do chamador."""
    if not isinstance(interaction.message, discord.Message):
        return
    try:
        disabled_view = purchase_approval_view(_payment_id_from_message(interaction.message))
        for item in disabled_view.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.message.edit(view=disabled_view)
    except (discord.HTTPException, ValueError):
        logger.warning("Falha ao desabilitar botoes de aprovacao na mensagem %s.", interaction.message.id)


def _payment_id_from_message(message: discord.Message) -> uuid.UUID:
    for row in message.components:
        for child in getattr(row, "children", []):
            custom_id = getattr(child, "custom_id", None) or ""
            match = re.search(r"limerence:payment_approval:\w+:([0-9a-fA-F-]{36})", custom_id)
            if match:
                return uuid.UUID(match.group(1))
    raise ValueError("payment_id não encontrado nos botões da mensagem.")


class PaymentApproveButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"limerence:payment_approval:approve:(?P<payment_id>[0-9a-fA-F-]{36})",
):
    def __init__(self, payment_id: uuid.UUID) -> None:
        super().__init__(
            discord.ui.Button(
                label="Aprovar", style=discord.ButtonStyle.success, emoji="✅",
                custom_id=f"limerence:payment_approval:approve:{payment_id}",
            )
        )
        self.payment_id = payment_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: "re.Match[str]"
    ) -> "PaymentApproveButton":
        return cls(uuid.UUID(match["payment_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if await _deny_if_not_admin(interaction):
            return
        bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
        await interaction.response.defer(ephemeral=True)
        subscription = await bot.subscription_service.confirm_payment(
            self.payment_id, executor=interaction.user
        )
        if subscription is None:
            await interaction.followup.send(
                "Esse pagamento não pode mais ser aprovado (não existe, ou já foi "
                "rejeitado/cancelado/expirado antes).",
                ephemeral=True,
            )
            await _disable_and_edit(interaction)
            return
        await _disable_and_edit(interaction)
        await interaction.followup.send("✅ Pagamento aprovado — cargo entregue.", ephemeral=True)


class PaymentRejectButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"limerence:payment_approval:reject:(?P<payment_id>[0-9a-fA-F-]{36})",
):
    def __init__(self, payment_id: uuid.UUID) -> None:
        super().__init__(
            discord.ui.Button(
                label="Rejeitar", style=discord.ButtonStyle.danger, emoji="❌",
                custom_id=f"limerence:payment_approval:reject:{payment_id}",
            )
        )
        self.payment_id = payment_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: "re.Match[str]"
    ) -> "PaymentRejectButton":
        return cls(uuid.UUID(match["payment_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if await _deny_if_not_admin(interaction):
            return
        bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
        await interaction.response.defer(ephemeral=True)
        changed = await bot.subscription_service.reject_payment(self.payment_id, executor=interaction.user)
        if not changed:
            await interaction.followup.send(
                "Esse pagamento não pode mais ser rejeitado (não está mais pendente).", ephemeral=True
            )
            return
        await _disable_and_edit(interaction)
        await interaction.followup.send("❌ Pagamento rejeitado.", ephemeral=True)


class PaymentPendingButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"limerence:payment_approval:pending:(?P<payment_id>[0-9a-fA-F-]{36})",
):
    def __init__(self, payment_id: uuid.UUID) -> None:
        super().__init__(
            discord.ui.Button(
                label="Marcar como Pendente", style=discord.ButtonStyle.secondary, emoji="⏳",
                custom_id=f"limerence:payment_approval:pending:{payment_id}",
            )
        )
        self.payment_id = payment_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: "re.Match[str]"
    ) -> "PaymentPendingButton":
        return cls(uuid.UUID(match["payment_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if await _deny_if_not_admin(interaction):
            return
        bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
        await interaction.response.defer(ephemeral=True)
        payment = await bot.subscription_service.mark_payment_pending(
            self.payment_id, executor=interaction.user
        )
        if payment is None:
            await interaction.followup.send(
                "Esse pagamento não pode voltar a pendente (já foi aprovado/cancelado, ou já está pendente).",
                ephemeral=True,
            )
            return
        await interaction.followup.send("⏳ Pagamento marcado como pendente novamente.", ephemeral=True)


class PaymentCancelButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"limerence:payment_approval:cancel:(?P<payment_id>[0-9a-fA-F-]{36})",
):
    def __init__(self, payment_id: uuid.UUID) -> None:
        super().__init__(
            discord.ui.Button(
                label="Cancelar Pedido", style=discord.ButtonStyle.secondary, emoji="🚫",
                custom_id=f"limerence:payment_approval:cancel:{payment_id}",
            )
        )
        self.payment_id = payment_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: "re.Match[str]"
    ) -> "PaymentCancelButton":
        return cls(uuid.UUID(match["payment_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if await _deny_if_not_admin(interaction):
            return
        bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
        await interaction.response.defer(ephemeral=True)
        changed = await bot.subscription_service.cancel_payment(self.payment_id, executor=interaction.user)
        if not changed:
            await interaction.followup.send(
                "Esse pedido não pode mais ser cancelado (já foi processado).", ephemeral=True
            )
            return
        await _disable_and_edit(interaction)
        await interaction.followup.send("🚫 Pedido cancelado.", ephemeral=True)


def purchase_approval_view(payment_id: uuid.UUID) -> discord.ui.View:
    """View persistente (sobrevive a restart) do painel de aprovacao manual —
    Aprovar/Rejeitar/Marcar como Pendente/Cancelar Pedido, um pedido por
    mensagem no canal de aprovacao."""
    view = SafeView(timeout=None)
    view.add_item(PaymentApproveButton(payment_id))
    view.add_item(PaymentRejectButton(payment_id))
    view.add_item(PaymentPendingButton(payment_id))
    view.add_item(PaymentCancelButton(payment_id))
    return view
