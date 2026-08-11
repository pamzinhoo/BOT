from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, Any

import discord

from database.models.subscription_renewal import (
    SubscriptionRenewalButton,
    SubscriptionRenewalButtonKey,
)
from views.base_view import SafeView

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_LABEL_FALLBACK = {
    SubscriptionRenewalButtonKey.RENEW: ("Renovar", "🔄"),
    SubscriptionRenewalButtonKey.VIEW_PLAN: ("Ver Plano", "📋"),
    SubscriptionRenewalButtonKey.OPEN_STORE: ("Abrir Loja", "🛒"),
    SubscriptionRenewalButtonKey.CLOSE: ("Fechar", "✖️"),
}

_STYLES = {
    SubscriptionRenewalButtonKey.RENEW: discord.ButtonStyle.success,
    SubscriptionRenewalButtonKey.VIEW_PLAN: discord.ButtonStyle.secondary,
    SubscriptionRenewalButtonKey.OPEN_STORE: discord.ButtonStyle.primary,
    SubscriptionRenewalButtonKey.CLOSE: discord.ButtonStyle.secondary,
}


async def _resolve_member(
    bot: LimerenceBot, guild_id: int, user_id: int
) -> discord.Member | None:
    """As mensagens de renovação vão por DM, onde `interaction.user` é um User e
    `interaction.guild` é None — o guild_id vem no custom_id justamente pra
    conseguir voltar pro Member antes de reaproveitar o fluxo da Loja."""
    guild = bot.get_guild(guild_id)
    if guild is None:
        return None
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except discord.HTTPException:
        return None


class RenewSubscriptionButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=(
        r"limerence:subrenew:renew:(?P<guild_id>\d+):(?P<subscription_id>[0-9a-fA-F-]{36})"
    ),
):
    """Botão 'Renovar' das mensagens de aviso. Não fala com gateway nenhum —
    chama o MESMO fluxo de compra da Loja (SubscriptionService.start_purchase →
    PaymentService → PaymentProvider), então qualquer gateway novo funciona sem
    tocar em nada aqui. Persistente: sobrevive a restart do bot."""

    def __init__(self, guild_id: int, subscription_id: uuid.UUID, *, label: str, emoji: str | None) -> None:
        super().__init__(
            discord.ui.Button(
                label=label,
                style=_STYLES[SubscriptionRenewalButtonKey.RENEW],
                emoji=emoji or None,
                custom_id=f"limerence:subrenew:renew:{guild_id}:{subscription_id}",
            )
        )
        self.guild_id = guild_id
        self.subscription_id = subscription_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]
    ) -> RenewSubscriptionButton:
        label, emoji = _LABEL_FALLBACK[SubscriptionRenewalButtonKey.RENEW]
        return cls(
            int(match["guild_id"]), uuid.UUID(match["subscription_id"]), label=label, emoji=emoji
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        from views.shop_view import start_purchase_flow

        # NAO deferir aqui, de proposito: start_purchase_flow() precisa da
        # interacao "fresca" (nao respondida ainda) pra poder abrir, ela
        # mesma, o prompt de cupom (send_message) ou o modal de "quem vai
        # pagar" (send_modal) como PRIMEIRA resposta — se ja tivermos dado
        # defer aqui, start_purchase_flow ve interaction.response.is_done()
        # e pula os dois passos silenciosamente, indo direto pra compra sem
        # cupom/sem payer_information. Os `await` abaixo (get_subscription,
        # get_plan, _resolve_member) ficam sem guarda de timeout como
        # contrapartida — e o mesmo trade-off que todo outro caller de
        # start_purchase_flow em shop_view.py aceita (nenhum deles deferre
        # antes de chamar).
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        subscription = await bot.subscription_service.get_subscription(self.subscription_id)
        if (
            subscription is None
            or subscription.user_id != interaction.user.id
            or subscription.guild_id != self.guild_id
        ):
            await interaction.response.send_message(
                "Esta assinatura não é sua ou não existe mais.", ephemeral=True
            )
            return
        plan = await bot.plan_service.get_plan(subscription.plan_id)
        if plan is None or not plan.is_active:
            await interaction.response.send_message(
                "O plano dessa assinatura não está mais disponível.", ephemeral=True
            )
            return
        member = await _resolve_member(bot, self.guild_id, interaction.user.id)
        if member is None:
            await interaction.response.send_message(
                "Não consegui te encontrar no servidor dessa assinatura.", ephemeral=True
            )
            return
        await start_purchase_flow(
            interaction, plan, subscription.billing_cycle, member=member, renewal=True
        )


class ViewPlanButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"limerence:subrenew:plan:(?P<guild_id>\d+):(?P<plan_id>[0-9a-fA-F-]{36})",
):
    """Mostra o card do plano (mesmo embed da Loja), sem iniciar compra."""

    def __init__(self, guild_id: int, plan_id: uuid.UUID, *, label: str, emoji: str | None) -> None:
        super().__init__(
            discord.ui.Button(
                label=label,
                style=_STYLES[SubscriptionRenewalButtonKey.VIEW_PLAN],
                emoji=emoji or None,
                custom_id=f"limerence:subrenew:plan:{guild_id}:{plan_id}",
            )
        )
        self.guild_id = guild_id
        self.plan_id = plan_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]
    ) -> ViewPlanButton:
        label, emoji = _LABEL_FALLBACK[SubscriptionRenewalButtonKey.VIEW_PLAN]
        return cls(int(match["guild_id"]), uuid.UUID(match["plan_id"]), label=label, emoji=emoji)

    async def callback(self, interaction: discord.Interaction) -> None:
        from views.shop_view import plan_card_embed

        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        # Deferir de imediato: get_plan + list_benefits sao duas idas ao banco
        # antes de termos algo pra mostrar.
        await interaction.response.defer()
        plan = await bot.plan_service.get_plan(self.plan_id)
        if plan is None:
            await interaction.followup.send("Plano não encontrado.", ephemeral=True)
            return
        benefits = [b.text for b in await bot.plan_service.list_benefits(plan.id)]
        await interaction.followup.send(
            embed=plan_card_embed(plan, benefits, position=0, total=1),
            ephemeral=interaction.guild is not None,
        )


class OpenStoreButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"limerence:subrenew:store:(?P<guild_id>\d+)",
):
    """Abre a Loja da guild (mesma ShopView de sempre) direto da DM."""

    def __init__(self, guild_id: int, *, label: str, emoji: str | None) -> None:
        super().__init__(
            discord.ui.Button(
                label=label,
                style=_STYLES[SubscriptionRenewalButtonKey.OPEN_STORE],
                emoji=emoji or None,
                custom_id=f"limerence:subrenew:store:{guild_id}",
            )
        )
        self.guild_id = guild_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]
    ) -> OpenStoreButton:
        label, emoji = _LABEL_FALLBACK[SubscriptionRenewalButtonKey.OPEN_STORE]
        return cls(int(match["guild_id"]), label=label, emoji=emoji)

    async def callback(self, interaction: discord.Interaction) -> None:
        from views.shop_view import ShopView

        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        # Deferir de imediato: list_plans + um list_benefits por plano + a
        # resolucao do member (pode cair em fetch_member, uma chamada HTTP)
        # facilmente somam mais que os 3s que o Discord da pra responder a
        # interacao antes de termos a ShopView pronta pra mostrar.
        await interaction.response.defer()
        plans = await bot.plan_service.list_plans(self.guild_id, only_active=True)
        if not plans:
            await interaction.followup.send("Nenhum plano disponível no momento.", ephemeral=True)
            return
        benefits_by_plan = {
            plan.id: [b.text for b in await bot.plan_service.list_benefits(plan.id)]
            for plan in plans
        }
        member = await _resolve_member(bot, self.guild_id, interaction.user.id)
        view = ShopView(plans, benefits_by_plan, member=member)
        await interaction.followup.send(
            embed=view.render_embed(), view=view, ephemeral=interaction.guild is not None
        )


class CloseRenewalMessageButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"limerence:subrenew:close",
):
    def __init__(self, *, label: str, emoji: str | None) -> None:
        super().__init__(
            discord.ui.Button(
                label=label,
                style=_STYLES[SubscriptionRenewalButtonKey.CLOSE],
                emoji=emoji or None,
                custom_id="limerence:subrenew:close",
            )
        )

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]
    ) -> CloseRenewalMessageButton:
        label, emoji = _LABEL_FALLBACK[SubscriptionRenewalButtonKey.CLOSE]
        return cls(label=label, emoji=emoji)

    async def callback(self, interaction: discord.Interaction) -> None:
        # Deferir de imediato: message.delete() e uma chamada HTTP e nao
        # precisamos de resposta visivel nenhuma no caminho feliz (a mensagem
        # some); so caimos pra editar quando o delete falha.
        await interaction.response.defer()
        message = interaction.message
        if message is not None:
            try:
                await message.delete()
                return
            except discord.HTTPException:
                pass
        await interaction.edit_original_response(view=None)


def build_renewal_message_view(
    *,
    guild_id: int,
    subscription_id: uuid.UUID,
    plan_id: uuid.UUID,
    buttons: list[SubscriptionRenewalButton],
) -> discord.ui.View | None:
    """Monta a view da mensagem de renovação só com os botões que a guild
    deixou ativos, na ordem configurada, com label/emoji personalizados."""
    view = SafeView(timeout=None)
    added = 0
    for button in sorted(buttons, key=lambda b: b.position):
        if not button.enabled:
            continue
        fallback_label, fallback_emoji = _LABEL_FALLBACK[button.key]
        label = button.label or fallback_label
        emoji = button.emoji if button.emoji is not None else fallback_emoji
        if button.key == SubscriptionRenewalButtonKey.RENEW:
            view.add_item(
                RenewSubscriptionButton(guild_id, subscription_id, label=label, emoji=emoji)
            )
        elif button.key == SubscriptionRenewalButtonKey.VIEW_PLAN:
            view.add_item(ViewPlanButton(guild_id, plan_id, label=label, emoji=emoji))
        elif button.key == SubscriptionRenewalButtonKey.OPEN_STORE:
            view.add_item(OpenStoreButton(guild_id, label=label, emoji=emoji))
        elif button.key == SubscriptionRenewalButtonKey.CLOSE:
            view.add_item(CloseRenewalMessageButton(label=label, emoji=emoji))
        added += 1
    return view if added else None


__all__: list[Any] = [
    "CloseRenewalMessageButton",
    "OpenStoreButton",
    "RenewSubscriptionButton",
    "ViewPlanButton",
    "build_renewal_message_view",
]
