from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import discord

from database.models.monetization_gateway_settings import MonetizationGatewaySettings
from database.models.monetization_settings import MonetizationSettings
from database.models.plan import Plan
from database.models.plan_message import PlanMessageType
from utils.constants import EMBED_COLOR_DEFAULT, EMBED_COLOR_WARNING
from views.base_view import SafeView
from views.settings_panel import DomainSettingsView, FieldKind, SettingsField

_GATEWAY_FIELDS = [
    SettingsField(
        "provider", "Gateway ativo", FieldKind.CHOICE, MonetizationGatewaySettings,
        choices=[("manual", "Manual (aprovação por staff)"), ("mercadopago", "Mercado Pago")],
    ),
    SettingsField(
        "environment", "Ambiente", FieldKind.CHOICE, MonetizationGatewaySettings,
        choices=[("sandbox", "Sandbox (testes)"), ("production", "Produção")],
    ),
    SettingsField(
        "currency", "Moeda", FieldKind.CHOICE, MonetizationGatewaySettings,
        choices=[("BRL", "Real (BRL)"), ("USD", "Dólar (USD)")],
    ),
    SettingsField(
        "pix_expiration_minutes", "Expiração do PIX (min)", FieldKind.NUMBER,
        MonetizationGatewaySettings, allow_clear=False,
    ),
    SettingsField("allow_one_time", "Permitir pagamento único", FieldKind.BOOL, MonetizationGatewaySettings),
    SettingsField("allow_recurring", "Permitir pagamentos recorrentes", FieldKind.BOOL, MonetizationGatewaySettings),
    SettingsField("enable_pix", "Ativar PIX", FieldKind.BOOL, MonetizationGatewaySettings),
    SettingsField("enable_card", "Ativar Cartão", FieldKind.BOOL, MonetizationGatewaySettings),
    SettingsField("enable_boleto", "Ativar Boleto", FieldKind.BOOL, MonetizationGatewaySettings),
]

if TYPE_CHECKING:
    from core.bot import LimerenceBot
    from database.models.plan_benefit import PlanBenefit

_MESSAGE_TYPE_LABELS = {
    PlanMessageType.PURCHASE: "Após compra",
    PlanMessageType.RENEWAL: "Renovação",
    PlanMessageType.CANCELLATION: "Cancelamento",
    PlanMessageType.THANK_YOU: "Agradecimento",
    PlanMessageType.UPGRADE: "Upgrade",
    PlanMessageType.DOWNGRADE: "Downgrade",
}

_LOJA_FIELDS = [
    SettingsField("shop_channel_id", "Canal da Loja", FieldKind.CHANNEL, MonetizationSettings),
    SettingsField("approval_channel_id", "Canal de Aprovação Manual", FieldKind.CHANNEL, MonetizationSettings),
    SettingsField("log_channel_id", "Canal de Logs", FieldKind.CHANNEL, MonetizationSettings),
    SettingsField(
        "dlc_announcement_channel_id", "Canal de Aviso de DLC Grátis", FieldKind.CHANNEL, MonetizationSettings
    ),
]


def monetization_menu_embed() -> discord.Embed:
    embed = discord.Embed(
        title="💰 Monetização",
        description=(
            "Sistema de Planos totalmente configurável. Nenhum plano é fixo — "
            "crie, edite e organize seus próprios planos de apoio."
        ),
        color=EMBED_COLOR_DEFAULT,
    )
    return embed


class MonetizationMenuView(SafeView):
    def __init__(self, on_back: Any = None) -> None:
        super().__init__(timeout=300)
        self.on_back = on_back
        if on_back is not None:
            self.add_item(_BackToMainMenuButton(on_back))

    @discord.ui.button(label="📋 Planos", style=discord.ButtonStyle.primary)
    async def plans_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        plans = await bot.plan_service.list_plans(interaction.guild_id)
        await interaction.edit_original_response(
            content=None, embed=plans_list_embed(plans), view=PlansListView(plans)
        )

    @discord.ui.button(label="⚙️ Configurações da Loja", style=discord.ButtonStyle.secondary)
    async def settings_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]

        async def get_settings(guild_id: int) -> MonetizationSettings:
            return await bot.subscription_service.get_settings(guild_id)

        async def update_settings(guild_id: int, **fields: object) -> MonetizationSettings:
            settings = await bot.subscription_service.update_settings(guild_id, **fields)
            new_channel_id = fields.get("shop_channel_id")
            if new_channel_id is not None:
                await bot.painel_service.publish_shop_panel(guild_id, int(new_channel_id))  # type: ignore[arg-type]
            return settings

        view = DomainSettingsView(
            title="💰 Monetização — Configurações",
            fields=_LOJA_FIELDS,
            get_settings=get_settings,
            update_settings=update_settings,
            on_back=_back_to_monetization_menu,
        )
        from views.settings_panel import build_domain_embed

        settings = await get_settings(interaction.guild_id)
        await interaction.edit_original_response(
            content=None, embed=build_domain_embed(view.title, view.fields, settings), view=view
        )

    @discord.ui.button(label="🔌 Gateway de Pagamentos", style=discord.ButtonStyle.secondary)
    async def gateway_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]

        async def get_settings(guild_id: int) -> MonetizationGatewaySettings:
            return await bot.payment_service.get_gateway_settings(guild_id)

        view = DomainSettingsView(
            title="🔌 Monetização — Gateway de Pagamentos",
            fields=_GATEWAY_FIELDS,
            get_settings=get_settings,
            update_settings=bot.payment_service.update_gateway_settings,
            on_back=_back_to_monetization_menu,
        )
        from views.settings_panel import build_domain_embed

        settings = await get_settings(interaction.guild_id)
        await interaction.edit_original_response(
            content=(
                "Credenciais do gateway (token/segredo) são configuradas só por variável de "
                "ambiente — nunca aparecem aqui nem em nenhuma embed."
            ),
            embed=build_domain_embed(view.title, view.fields, settings), view=view
        )

    @discord.ui.button(label="🧾 PIX Manual", style=discord.ButtonStyle.secondary)
    async def pix_manual_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from views.pix_manual_panel_view import render_pix_manual_menu

        await render_pix_manual_menu(interaction)

    @discord.ui.button(label="🔁 Renovação de Assinaturas", style=discord.ButtonStyle.secondary)
    async def renewal_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from views.subscription_renewal_view import render_renewal_menu

        await render_renewal_menu(interaction)

    @discord.ui.button(label="📨 Mensagens ao Comprador", style=discord.ButtonStyle.secondary)
    async def payment_dm_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from views.payment_dm_panel_view import render_payment_dm_menu

        await render_payment_dm_menu(interaction)

    @discord.ui.button(label="🎟️ Cupons", style=discord.ButtonStyle.secondary)
    async def coupons_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from views.coupon_panel_view import render_coupons_menu

        await render_coupons_menu(interaction)

    @discord.ui.button(label="🎮 DLC", style=discord.ButtonStyle.secondary)
    async def dlc_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        from views.dlc_panel_view import DlcListView, dlc_list_embed

        dlcs = await bot.dlc_service.list_dlcs()
        await interaction.edit_original_response(content=None, embed=dlc_list_embed(dlcs), view=DlcListView(dlcs))


async def _back_to_monetization_menu(interaction: discord.Interaction) -> None:
    await interaction.response.edit_message(
        content=None, embed=monetization_menu_embed(), view=MonetizationMenuView()
    )


class _BackToMainMenuButton(discord.ui.Button[Any]):
    def __init__(self, on_back: Any) -> None:
        super().__init__(label="◀ Menu principal", style=discord.ButtonStyle.secondary, row=4)
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.on_back(interaction)


def plans_list_embed(plans: list[Plan]) -> discord.Embed:
    embed = discord.Embed(title="📋 Planos cadastrados", color=EMBED_COLOR_DEFAULT)
    if not plans:
        embed.description = "Nenhum plano cadastrado ainda. Use o menu abaixo pra criar o primeiro."
    else:
        for plan in plans:
            status = "✅ Ativo" if plan.is_active else "🚫 Inativo"
            recommended = " ⭐" if plan.is_recommended else ""
            embed.add_field(
                name=f"{plan.emoji or ''} {plan.name}{recommended}".strip(),
                value=status,
                inline=True,
            )
    return embed


class PlansListView(SafeView):
    def __init__(self, plans: list[Plan]) -> None:
        super().__init__(timeout=300)
        self.plans = plans
        if plans:
            self.add_item(_PlanSelect(plans))
        self.add_item(_CreatePlanButton())
        self.add_item(_BackToMonetizationMenuButton())


class _PlanSelect(discord.ui.Select[Any]):
    def __init__(self, plans: list[Plan]) -> None:
        options = [
            discord.SelectOption(label=f"{p.emoji or ''} {p.name}".strip(), value=str(p.id))
            for p in plans
        ][:25]
        super().__init__(placeholder="Selecione um plano pra editar...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        plan = await bot.plan_service.get_plan(uuid.UUID(self.values[0]))
        if plan is None or plan.guild_id != interaction.guild_id:
            await interaction.followup.send("Plano não encontrado.", ephemeral=True)
            return
        await interaction.edit_original_response(
            content=None, embed=await _plan_edit_embed(bot, plan), view=PlanEditView(plan)
        )


class _CreatePlanButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(label="➕ Criar Plano", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(_CreatePlanModal())


class _CreatePlanModal(discord.ui.Modal, title="Criar Plano"):
    name_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Nome do plano", placeholder="Ex: VIP, Premium, Apoiador...", max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        try:
            plan = await bot.plan_service.create_plan(
                interaction.guild_id, str(self.name_input.value).strip(), executor=interaction.user
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.edit_original_response(
            content=None, embed=await _plan_edit_embed(bot, plan, benefits=[]), view=PlanEditView(plan)
        )
        await bot.painel_service.refresh_shop_panel(interaction.guild_id)


class _BackToMonetizationMenuButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        await _back_to_monetization_menu(interaction)


async def _plan_edit_embed(
    bot: LimerenceBot, plan: Plan, *, benefits: list[PlanBenefit] | None = None
) -> discord.Embed:
    if benefits is None:
        benefits = await bot.plan_service.list_benefits(plan.id)
    color = discord.Color(plan.color) if plan.color is not None else EMBED_COLOR_WARNING
    embed = discord.Embed(title=f"{plan.emoji or ''} {plan.name}".strip(), color=color)
    embed.description = plan.description or "*(sem descrição)*"
    embed.add_field(name="Status", value="✅ Ativo" if plan.is_active else "🚫 Inativo")
    embed.add_field(name="Recomendado", value="⭐ Sim" if plan.is_recommended else "Não")
    embed.add_field(name="Ordem", value=str(plan.position))
    embed.add_field(
        name="Preço mensal", value=f"{plan.currency} {plan.price_monthly / 100:.2f}" if plan.price_monthly else "—"
    )
    embed.add_field(
        name="Preço anual", value=f"{plan.currency} {plan.price_yearly / 100:.2f}" if plan.price_yearly else "—"
    )
    embed.add_field(
        name="Pagamento único",
        value=f"{plan.currency} {plan.price_one_time / 100:.2f}" if plan.price_one_time else "—",
    )
    embed.add_field(name="Cargo", value=f"<@&{plan.role_id}>" if plan.role_id else "—")
    weight = None
    if plan.role_id is not None:
        weights = await bot.vote_weight_service.get_weights(plan.guild_id)
        weight = next((w.weight for w in weights if w.role_id == plan.role_id), None)
    embed.add_field(name="⚖️ Peso de Voto", value=str(weight) if weight is not None else "— (padrão: 1)")
    embed.add_field(
        name="Benefícios",
        value="\n".join(f"✔ {b.text}" for b in benefits) if benefits else "—",
        inline=False,
    )
    return embed


class PlanEditView(SafeView):
    def __init__(self, plan: Plan) -> None:
        super().__init__(timeout=300)
        self.plan = plan

    @discord.ui.button(label="✏️ Info", style=discord.ButtonStyle.primary, row=0)
    async def info_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(_PlanInfoModal(self.plan))

    @discord.ui.button(label="💲 Preços", style=discord.ButtonStyle.primary, row=0)
    async def price_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(_PlanPriceModal(self.plan))

    @discord.ui.button(label="🎨 Cor", style=discord.ButtonStyle.primary, row=0)
    async def color_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(_PlanColorModal(self.plan))

    @discord.ui.button(label="🔢 Ordem", style=discord.ButtonStyle.primary, row=0)
    async def position_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(_PlanPositionModal(self.plan))

    @discord.ui.button(label="🎭 Cargo", style=discord.ButtonStyle.secondary, row=1)
    async def role_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        view = SafeView(timeout=120)
        view.add_item(_RolePicker(self.plan))
        await interaction.response.edit_message(content="Selecione o cargo entregue por este plano:", embed=None, view=view)

    @discord.ui.button(label="📜 Benefícios", style=discord.ButtonStyle.secondary, row=1)
    async def benefits_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        benefits = await bot.plan_service.list_benefits(self.plan.id)
        await interaction.response.send_modal(_BenefitsModal(self.plan, benefits))

    @discord.ui.button(label="💬 Mensagens", style=discord.ButtonStyle.secondary, row=1)
    async def messages_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        view = SafeView(timeout=120)
        view.add_item(_MessageTypeSelect(self.plan))
        view.add_item(_BackToPlanEditButton(self.plan))
        await interaction.response.edit_message(content="Escolha qual mensagem editar:", embed=None, view=view)

    @discord.ui.button(label="⚖️ Peso de Voto", style=discord.ButtonStyle.secondary, row=1)
    async def vote_weight_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.plan.role_id is None:
            await interaction.response.send_message(
                "Configure um cargo pra este plano antes de definir o peso de voto.", ephemeral=True
            )
            return
        await interaction.response.send_modal(_VoteWeightModal(self.plan))

    @discord.ui.button(label="⭐ Recomendado", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_recommended(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        plan = await bot.plan_service.update_plan(
            self.plan.id, is_recommended=not self.plan.is_recommended, executor=interaction.user
        )
        await _render_plan_edit(interaction, plan)

    @discord.ui.button(label="✅ Ativo/Inativo", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_active(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        plan = await bot.plan_service.update_plan(
            self.plan.id, is_active=not self.plan.is_active, executor=interaction.user
        )
        await _render_plan_edit(interaction, plan)

    @discord.ui.button(label="🗑️ Excluir", style=discord.ButtonStyle.danger, row=2)
    async def delete_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        view = SafeView(timeout=60)
        view.add_item(_ConfirmDeleteButton(self.plan))
        view.add_item(_BackToPlanEditButton(self.plan))
        await interaction.response.edit_message(
            content=f"Tem certeza que deseja excluir **{self.plan.name}**? Assinaturas existentes serão mantidas no histórico.",
            embed=None,
            view=view,
        )

    @discord.ui.button(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        plans = await bot.plan_service.list_plans(interaction.guild_id)
        await interaction.edit_original_response(content=None, embed=plans_list_embed(plans), view=PlansListView(plans))


async def _render_plan_edit(interaction: discord.Interaction, plan: Plan) -> None:
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    if interaction.response.is_done():
        await interaction.edit_original_response(embed=await _plan_edit_embed(bot, plan), view=PlanEditView(plan))
    else:
        await interaction.response.edit_message(embed=await _plan_edit_embed(bot, plan), view=PlanEditView(plan))
    if interaction.guild_id is not None:
        await bot.painel_service.refresh_shop_panel(interaction.guild_id)


class _BackToPlanEditButton(discord.ui.Button[Any]):
    def __init__(self, plan: Plan) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary)
        self.plan = plan

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await _render_plan_edit(interaction, self.plan)


class _ConfirmDeleteButton(discord.ui.Button[Any]):
    def __init__(self, plan: Plan) -> None:
        super().__init__(label="Confirmar exclusão", style=discord.ButtonStyle.danger)
        self.plan = plan

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        await bot.plan_service.delete_plan(self.plan.id, executor=interaction.user)
        plans = await bot.plan_service.list_plans(interaction.guild_id)
        await interaction.edit_original_response(content=None, embed=plans_list_embed(plans), view=PlansListView(plans))
        await bot.painel_service.refresh_shop_panel(interaction.guild_id)


class _RolePicker(discord.ui.RoleSelect):
    def __init__(self, plan: Plan) -> None:
        super().__init__(placeholder="Cargo entregue por este plano", min_values=1, max_values=1)
        self.plan = plan

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        plan = await bot.plan_service.update_plan(
            self.plan.id, role_id=self.values[0].id, executor=interaction.user
        )
        await _render_plan_edit(interaction, plan)


class _MessageTypeSelect(discord.ui.Select[Any]):
    def __init__(self, plan: Plan) -> None:
        options = [
            discord.SelectOption(label=label, value=message_type.value)
            for message_type, label in _MESSAGE_TYPE_LABELS.items()
        ]
        super().__init__(placeholder="Tipo de mensagem...", options=options, min_values=1, max_values=1)
        self.plan = plan

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        message_type = PlanMessageType(self.values[0])
        record = await bot.plan_service.get_message(self.plan.id, message_type)
        await interaction.response.send_modal(
            _MessageEditModal(self.plan, message_type, record.content if record else "")
        )


class _PlanInfoModal(discord.ui.Modal, title="Editar informações"):
    def __init__(self, plan: Plan) -> None:
        super().__init__()
        self.plan = plan
        self.name_input = discord.ui.TextInput(label="Nome", default=plan.name, max_length=100)
        self.emoji_input = discord.ui.TextInput(
            label="Emoji", default=plan.emoji or "", required=False, max_length=64
        )
        self.description_input = discord.ui.TextInput(
            label="Descrição (aparece na loja)",
            style=discord.TextStyle.paragraph,
            default=plan.description or "",
            required=False,
            max_length=1000,
        )
        self.add_item(self.name_input)
        self.add_item(self.emoji_input)
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        plan = await bot.plan_service.update_plan(
            self.plan.id,
            name=str(self.name_input.value).strip(),
            emoji=str(self.emoji_input.value).strip() or None,
            description=str(self.description_input.value).strip() or None,
            executor=interaction.user,
        )
        await _render_plan_edit(interaction, plan)


def _parse_reais(raw: str) -> int | None:
    raw = raw.strip().replace(",", ".")
    if not raw:
        return None
    return round(float(raw) * 100)


class _PlanPriceModal(discord.ui.Modal, title="Editar preços"):
    def __init__(self, plan: Plan) -> None:
        super().__init__()
        self.plan = plan
        self.monthly_input = discord.ui.TextInput(
            label="Preço mensal (ex: 19.90)",
            default=f"{plan.price_monthly / 100:.2f}" if plan.price_monthly else "",
            required=False,
            max_length=12,
        )
        self.yearly_input = discord.ui.TextInput(
            label="Preço anual (ex: 199.90)",
            default=f"{plan.price_yearly / 100:.2f}" if plan.price_yearly else "",
            required=False,
            max_length=12,
        )
        self.one_time_input = discord.ui.TextInput(
            label="Pagamento único (ex: 49.90)",
            default=f"{plan.price_one_time / 100:.2f}" if plan.price_one_time else "",
            required=False,
            max_length=12,
        )
        self.add_item(self.monthly_input)
        self.add_item(self.yearly_input)
        self.add_item(self.one_time_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        try:
            monthly = _parse_reais(str(self.monthly_input.value))
            yearly = _parse_reais(str(self.yearly_input.value))
            one_time = _parse_reais(str(self.one_time_input.value))
        except ValueError:
            await interaction.response.send_message("Preço inválido — use números (ex: 19.90).", ephemeral=True)
            return
        await interaction.response.defer()
        plan = await bot.plan_service.update_plan(
            self.plan.id, price_monthly=monthly, price_yearly=yearly, price_one_time=one_time,
            executor=interaction.user,
        )
        await _render_plan_edit(interaction, plan)


class _PlanColorModal(discord.ui.Modal, title="Editar cor"):
    color_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Cor em hexadecimal", placeholder="Ex: #5865F2", required=False, max_length=7
    )

    def __init__(self, plan: Plan) -> None:
        super().__init__()
        self.plan = plan
        if plan.color is not None:
            self.color_input.default = f"#{plan.color:06X}"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        raw = str(self.color_input.value).strip().lstrip("#")
        if not raw:
            await interaction.response.defer()
            plan = await bot.plan_service.update_plan(self.plan.id, color=None, executor=interaction.user)
            await _render_plan_edit(interaction, plan)
            return
        try:
            value = int(raw, 16)
        except ValueError:
            await interaction.response.send_message("Cor inválida — use um hexadecimal (ex: #5865F2).", ephemeral=True)
            return
        await interaction.response.defer()
        plan = await bot.plan_service.update_plan(self.plan.id, color=value, executor=interaction.user)
        await _render_plan_edit(interaction, plan)


class _PlanPositionModal(discord.ui.Modal, title="Editar ordem"):
    position_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Posição (menor aparece primeiro)", max_length=4
    )

    def __init__(self, plan: Plan) -> None:
        super().__init__()
        self.plan = plan
        self.position_input.default = str(plan.position)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        raw = str(self.position_input.value).strip()
        if not raw.lstrip("-").isdigit():
            await interaction.response.send_message("Digite um número inteiro.", ephemeral=True)
            return
        await interaction.response.defer()
        plan = await bot.plan_service.update_plan(self.plan.id, position=int(raw), executor=interaction.user)
        await _render_plan_edit(interaction, plan)


class _BenefitsModal(discord.ui.Modal, title="Editar benefícios"):
    benefits_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="1 benefício por linha",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=2000,
    )

    def __init__(self, plan: Plan, benefits: list) -> None:
        super().__init__()
        self.plan = plan
        self.benefits_input.default = "\n".join(b.text for b in benefits)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        lines = str(self.benefits_input.value).splitlines()
        await bot.plan_service.set_benefits(self.plan.id, lines, executor=interaction.user)
        await _render_plan_edit(interaction, self.plan)


class _VoteWeightModal(discord.ui.Modal, title="Peso de voto do plano"):
    weight_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Peso de voto (número inteiro maior que zero)", placeholder="Ex: 3", max_length=6
    )

    def __init__(self, plan: Plan) -> None:
        super().__init__()
        self.plan = plan

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        raw = str(self.weight_input.value).strip()
        if not raw.isdigit() or int(raw) <= 0:
            await interaction.response.send_message(
                "Digite um número inteiro maior que zero.", ephemeral=True
            )
            return
        await interaction.response.defer()
        await bot.vote_weight_service.sync_plan_benefit_weight(interaction.guild_id, self.plan, int(raw))
        await _render_plan_edit(interaction, self.plan)


class _MessageEditModal(discord.ui.Modal):
    content_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Mensagem",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=2000,
    )

    def __init__(self, plan: Plan, message_type: PlanMessageType, current: str) -> None:
        super().__init__(title=f"Mensagem — {_MESSAGE_TYPE_LABELS[message_type]}"[:45])
        self.plan = plan
        self.message_type = message_type
        self.content_input.default = current
        self.content_input.placeholder = (
            "Placeholders: {user} {server_name} {plan_name} {plan_price} {role_name} {renew_date} {guild_members}"
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        content = str(self.content_input.value).strip()
        if content:
            await bot.plan_service.set_message(self.plan.id, self.message_type, content)
        await _render_plan_edit(interaction, self.plan)
