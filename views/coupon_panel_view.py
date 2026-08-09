from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import discord

from database.models.audit_log import AuditLogCategory
from database.models.discount_coupon import DiscountCoupon, DiscountType
from database.models.plan import Plan
from database.models.subscription import BillingCycle
from services.coupon_service import CouponError, CouponStats, format_discount
from utils.constants import EMBED_COLOR_DEFAULT, EMBED_COLOR_PURPLE
from views.base_view import SafeView

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_CYCLE_LABELS = {
    BillingCycle.MONTHLY: "Mensal",
    BillingCycle.YEARLY: "Anual",
    BillingCycle.ONE_TIME: "Pagamento único",
}

_DISCOUNT_TYPE_LABELS = {
    DiscountType.PERCENTAGE: "Porcentagem (%)",
    DiscountType.FIXED: "Valor fixo (R$)",
}

_DATE_FORMAT = "%d/%m/%Y"


# --- helpers ---------------------------------------------------------------


def _parse_date(raw: str) -> datetime | None:
    """`DD/MM/AAAA` -> datetime UTC. Vazio -> None (sem restrição)."""
    raw = raw.strip()
    if not raw:
        return None
    return datetime.strptime(raw, _DATE_FORMAT).replace(tzinfo=UTC)


def _format_date(value: datetime | None) -> str:
    return value.strftime(_DATE_FORMAT) if value is not None else "—"


def _parse_optional_int(raw: str) -> int | None:
    """Campo numérico vazio = ilimitado (∞)."""
    raw = raw.strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise ValueError("Use apenas números inteiros (ou deixe vazio para ilimitado).")
    return int(raw)


async def _audit_coupon(
    interaction: discord.Interaction, coupon: DiscountCoupon, action: str, **details: object
) -> None:
    """Toda edição de cupom passa pelo audit_log_service existente — nenhuma
    plumbing nova de log."""
    assert interaction.guild_id is not None
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    await bot.audit_log_service.record(
        guild_id=interaction.guild_id,
        category=AuditLogCategory.COUPON,
        action=action,
        executor_id=interaction.user.id,
        executor_name=str(interaction.user),
        details={"cupom": coupon.code, **details},
    )


# --- menu principal de cupons ----------------------------------------------


def coupons_menu_embed() -> discord.Embed:
    return discord.Embed(
        title="🎟️ Cupons de Desconto",
        description=(
            "Cupons totalmente configuráveis por servidor. Nenhum código ou desconto é "
            "fixo — crie, edite, limite por plano/ciclo/cargo e acompanhe o uso."
        ),
        color=EMBED_COLOR_PURPLE,
    )


class CouponsMenuView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="➕ Criar Cupom", style=discord.ButtonStyle.success, row=0)
    async def create_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await interaction.response.send_modal(_CreateCouponModal())

    @discord.ui.button(label="📋 Gerenciar Cupons", style=discord.ButtonStyle.primary, row=0)
    async def manage_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        coupons = await bot.coupon_service.list_coupons(interaction.guild_id)
        await interaction.response.edit_message(
            content=None, embed=coupons_list_embed(coupons), view=CouponsListView(coupons)
        )

    @discord.ui.button(label="📊 Estatísticas", style=discord.ButtonStyle.secondary, row=1)
    async def stats_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        coupons = await bot.coupon_service.list_coupons(interaction.guild_id)
        if not coupons:
            await interaction.response.send_message(
                "Nenhum cupom cadastrado ainda.", ephemeral=True
            )
            return
        view = SafeView(timeout=300)
        view.add_item(_CouponStatsSelect(coupons))
        view.add_item(_BackToCouponsMenuButton())
        await interaction.response.edit_message(
            content="Selecione um cupom para ver as estatísticas:", embed=None, view=view
        )

    @discord.ui.button(label="⚙️ Configurações", style=discord.ButtonStyle.secondary, row=1)
    async def settings_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        coupons = await bot.coupon_service.list_coupons(interaction.guild_id)
        active = sum(1 for c in coupons if c.active)
        # Tela deliberadamente enxuta: TODA regra de cupom (validade, limites,
        # planos, ciclos, cargo, acúmulo) é por cupom. Não existe ajuste
        # global que faça sentido hoje — inventar um só criaria configuração
        # sem efeito.
        embed = discord.Embed(
            title="⚙️ Cupons — Configurações",
            description=(
                "Não há configuração global de cupons: cada cupom carrega suas próprias "
                "regras (validade, limites, planos, modalidades, cargo obrigatório e "
                "acúmulo), editáveis em **📋 Gerenciar Cupons**.\n\n"
                "Os eventos de cupom (criado/editado/ativado/desativado/removido/"
                "utilizado/expirado/limite atingido) são registrados na categoria "
                "**🎟️ Cupom** da Auditoria, que pode ser ligada/desligada em "
                "`/config painel > Auditoria`."
            ),
            color=EMBED_COLOR_DEFAULT,
        )
        embed.add_field(name="Cupons cadastrados", value=str(len(coupons)))
        embed.add_field(name="Cupons ativos", value=str(active))
        view = SafeView(timeout=300)
        view.add_item(_BackToCouponsMenuButton())
        await interaction.response.edit_message(content=None, embed=embed, view=view)

    @discord.ui.button(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        from views.monetization_panel_view import MonetizationMenuView, monetization_menu_embed

        await interaction.response.edit_message(
            content=None, embed=monetization_menu_embed(), view=MonetizationMenuView()
        )


async def render_coupons_menu(interaction: discord.Interaction) -> None:
    await interaction.response.edit_message(
        content=None, embed=coupons_menu_embed(), view=CouponsMenuView()
    )


class _BackToCouponsMenuButton(discord.ui.Button[Any]):
    def __init__(self, *, row: int | None = None) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        await render_coupons_menu(interaction)


# --- criacao ---------------------------------------------------------------


class _CreateCouponModal(discord.ui.Modal, title="Criar Cupom"):
    code_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Nome do cupom (código)", placeholder="Ex: PROMO10, BLACKFRIDAY...", max_length=64
    )
    description_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Descrição (opcional)", required=False, max_length=500,
        style=discord.TextStyle.paragraph,
    )
    emoji_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Emoji (opcional)", required=False, max_length=64
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        try:
            coupon = await bot.coupon_service.create_coupon(
                interaction.guild_id,
                str(self.code_input.value),
                description=str(self.description_input.value).strip() or None,
                emoji=str(self.emoji_input.value).strip() or None,
            )
        except CouponError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await _audit_coupon(interaction, coupon, "Cupom criado")
        await interaction.response.edit_message(
            content=(
                "Cupom criado! Configure o **💸 Desconto** para ele começar a valer "
                "(o valor padrão é 0)."
            ),
            embed=await _coupon_edit_embed(interaction, coupon),
            view=CouponEditView(coupon),
        )


# --- listagem --------------------------------------------------------------


def coupons_list_embed(coupons: list[DiscountCoupon]) -> discord.Embed:
    embed = discord.Embed(title="📋 Cupons cadastrados", color=EMBED_COLOR_PURPLE)
    if not coupons:
        embed.description = "Nenhum cupom cadastrado ainda. Use **➕ Criar Cupom**."
        return embed
    for coupon in coupons:
        status = "✅ Ativo" if coupon.active else "🚫 Inativo"
        embed.add_field(
            name=f"{coupon.emoji or '🎟️'} {coupon.code}",
            value=f"{status} · {format_discount(coupon)}",
            inline=True,
        )
    return embed


class CouponsListView(SafeView):
    def __init__(self, coupons: list[DiscountCoupon]) -> None:
        super().__init__(timeout=300)
        if coupons:
            self.add_item(_CouponSelect(coupons))
        self.add_item(_BackToCouponsMenuButton(row=1))


class _CouponSelect(discord.ui.Select[Any]):
    def __init__(self, coupons: list[DiscountCoupon]) -> None:
        options = [
            discord.SelectOption(
                label=f"{coupon.emoji or '🎟️'} {coupon.code}"[:100],
                value=str(coupon.id),
                description=format_discount(coupon),
            )
            for coupon in coupons
        ][:25]
        super().__init__(
            placeholder="Selecione um cupom pra editar...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        coupon = await _load_coupon(interaction, uuid.UUID(self.values[0]))
        if coupon is None:
            return
        await interaction.response.edit_message(
            content=None,
            embed=await _coupon_edit_embed(interaction, coupon),
            view=CouponEditView(coupon),
        )


async def _load_coupon(
    interaction: discord.Interaction, coupon_id: uuid.UUID
) -> DiscountCoupon | None:
    """Recarrega o cupom SEMPRE conferindo a guild — nenhuma tela pode operar
    sobre cupom de outro servidor, nem por custom_id forjado."""
    assert interaction.guild_id is not None
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    coupon = await bot.coupon_service.get_coupon(coupon_id)
    if coupon is None or coupon.guild_id != interaction.guild_id:
        if not interaction.response.is_done():
            await interaction.response.send_message("Cupom não encontrado.", ephemeral=True)
        return None
    return coupon


# --- editor ----------------------------------------------------------------


async def _coupon_edit_embed(
    interaction: discord.Interaction, coupon: DiscountCoupon
) -> discord.Embed:
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    plan_ids = await bot.coupon_service.list_allowed_plans(coupon.id)
    plans = await bot.plan_service.list_plans(coupon.guild_id)
    plan_names = [p.name for p in plans if p.id in set(plan_ids)]
    cycles = list(coupon.billing_cycles or [])

    embed = discord.Embed(
        title=f"{coupon.emoji or '🎟️'} {coupon.code}",
        description=coupon.description or "*(sem descrição)*",
        color=EMBED_COLOR_PURPLE,
    )
    embed.add_field(name="Status", value="✅ Ativo" if coupon.active else "🚫 Inativo")
    embed.add_field(name="Desconto", value=format_discount(coupon))
    embed.add_field(name="Acúmulo", value="Sim" if coupon.allow_stack else "Não")
    embed.add_field(
        name="Planos válidos", value=", ".join(plan_names) if plan_names else "Todos"
    )
    embed.add_field(
        name="Modalidades",
        value=", ".join(_CYCLE_LABELS[BillingCycle(c)] for c in cycles) if cycles else "Todas",
    )
    embed.add_field(
        name="Cargo obrigatório",
        value=f"<@&{coupon.required_role_id}>" if coupon.required_role_id else "—",
    )
    embed.add_field(name="Início", value=_format_date(coupon.starts_at))
    embed.add_field(name="Expira em", value=_format_date(coupon.expires_at))
    embed.add_field(
        name="Limites",
        value=(
            f"Global: {coupon.max_global_uses if coupon.max_global_uses is not None else '∞'} · "
            f"Por usuário: "
            f"{coupon.max_uses_per_user if coupon.max_uses_per_user is not None else '∞'}"
        ),
    )
    return embed


async def _render_coupon_edit(interaction: discord.Interaction, coupon: DiscountCoupon) -> None:
    embed = await _coupon_edit_embed(interaction, coupon)
    view = CouponEditView(coupon)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embed=embed, view=view)
    else:
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class CouponEditView(SafeView):
    def __init__(self, coupon: DiscountCoupon) -> None:
        super().__init__(timeout=300)
        self.coupon = coupon

    @discord.ui.button(label="✏️ Informações", style=discord.ButtonStyle.primary, row=0)
    async def info_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await interaction.response.send_modal(_CouponInfoModal(self.coupon))

    @discord.ui.button(label="💸 Desconto", style=discord.ButtonStyle.primary, row=0)
    async def discount_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        view = SafeView(timeout=120)
        view.add_item(_DiscountTypeSelect(self.coupon))
        view.add_item(_BackToCouponEditButton(self.coupon))
        await interaction.response.edit_message(
            content="Escolha o tipo de desconto:", embed=None, view=view
        )

    @discord.ui.button(label="📆 Validade", style=discord.ButtonStyle.primary, row=0)
    async def validity_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await interaction.response.send_modal(_CouponDatesModal(self.coupon))

    @discord.ui.button(label="🔢 Limites", style=discord.ButtonStyle.primary, row=0)
    async def limits_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await interaction.response.send_modal(_CouponLimitsModal(self.coupon))

    @discord.ui.button(label="📋 Planos válidos", style=discord.ButtonStyle.secondary, row=1)
    async def plans_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        plans = await bot.plan_service.list_plans(interaction.guild_id)
        if not plans:
            await interaction.response.send_message(
                "Nenhum plano cadastrado ainda — o cupom já vale para todos.", ephemeral=True
            )
            return
        selected = await bot.coupon_service.list_allowed_plans(self.coupon.id)
        view = SafeView(timeout=120)
        view.add_item(_CouponPlansSelect(self.coupon, plans, selected))
        view.add_item(_BackToCouponEditButton(self.coupon))
        await interaction.response.edit_message(
            content="Selecione os planos válidos (nenhum selecionado = **todos**):",
            embed=None,
            view=view,
        )

    @discord.ui.button(label="🔁 Modalidades", style=discord.ButtonStyle.secondary, row=1)
    async def cycles_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        view = SafeView(timeout=120)
        view.add_item(_CouponCyclesSelect(self.coupon))
        view.add_item(_BackToCouponEditButton(self.coupon))
        await interaction.response.edit_message(
            content="Selecione as modalidades de cobrança (nenhuma = **todas**):",
            embed=None,
            view=view,
        )

    @discord.ui.button(label="🎭 Cargo obrigatório", style=discord.ButtonStyle.secondary, row=1)
    async def role_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        view = SafeView(timeout=120)
        view.add_item(_CouponRolePicker(self.coupon))
        view.add_item(_ClearRequiredRoleButton(self.coupon))
        view.add_item(_BackToCouponEditButton(self.coupon))
        await interaction.response.edit_message(
            content="Selecione o cargo exigido para usar este cupom:", embed=None, view=view
        )

    @discord.ui.button(label="✅ Ativo/Inativo", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_active(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        coupon = await bot.coupon_service.set_active(
            self.coupon.id, not self.coupon.active, executor=interaction.user
        )
        await _render_coupon_edit(interaction, coupon)

    @discord.ui.button(label="➕ Acúmulo", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_stack(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        coupon = await bot.coupon_service.update_coupon(
            self.coupon.id, allow_stack=not self.coupon.allow_stack
        )
        await _audit_coupon(
            interaction, coupon, "Cupom editado", campo="Acúmulo", valor=coupon.allow_stack
        )
        await _render_coupon_edit(interaction, coupon)

    @discord.ui.button(label="📄 Duplicar", style=discord.ButtonStyle.secondary, row=2)
    async def duplicate_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        try:
            clone = await bot.coupon_service.duplicate_coupon(
                self.coupon.id, executor=interaction.user
            )
        except CouponError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.edit_message(
            content=f"Cupom duplicado como **{clone.code}**.",
            embed=await _coupon_edit_embed(interaction, clone),
            view=CouponEditView(clone),
        )

    @discord.ui.button(label="🗑️ Excluir", style=discord.ButtonStyle.danger, row=2)
    async def delete_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        view = SafeView(timeout=60)
        view.add_item(_ConfirmDeleteCouponButton(self.coupon))
        view.add_item(_BackToCouponEditButton(self.coupon))
        await interaction.response.edit_message(
            content=(
                f"Tem certeza que deseja excluir **{self.coupon.code}**? "
                "O histórico de utilizações nunca é apagado — se o cupom já foi usado, "
                "ele é arquivado (fica inativo e some das listagens)."
            ),
            embed=None,
            view=view,
        )

    @discord.ui.button(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        coupons = await bot.coupon_service.list_coupons(interaction.guild_id)
        await interaction.response.edit_message(
            content=None, embed=coupons_list_embed(coupons), view=CouponsListView(coupons)
        )


class _BackToCouponEditButton(discord.ui.Button[Any]):
    def __init__(self, coupon: DiscountCoupon) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary)
        self.coupon = coupon

    async def callback(self, interaction: discord.Interaction) -> None:
        coupon = await _load_coupon(interaction, self.coupon.id)
        if coupon is None:
            return
        await _render_coupon_edit(interaction, coupon)


class _ConfirmDeleteCouponButton(discord.ui.Button[Any]):
    def __init__(self, coupon: DiscountCoupon) -> None:
        super().__init__(label="Confirmar exclusão", style=discord.ButtonStyle.danger)
        self.coupon = coupon

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        hard = await bot.coupon_service.delete_coupon(self.coupon.id, executor=interaction.user)
        coupons = await bot.coupon_service.list_coupons(interaction.guild_id)
        await interaction.response.edit_message(
            content=(
                f"Cupom **{self.coupon.code}** excluído."
                if hard
                else f"Cupom **{self.coupon.code}** arquivado — o histórico de uso foi mantido."
            ),
            embed=coupons_list_embed(coupons),
            view=CouponsListView(coupons),
        )


# --- modais ----------------------------------------------------------------


class _CouponInfoModal(discord.ui.Modal, title="Editar informações"):
    def __init__(self, coupon: DiscountCoupon) -> None:
        super().__init__()
        self.coupon = coupon
        self.code_input = discord.ui.TextInput(
            label="Nome do cupom (código)", default=coupon.code, max_length=64
        )
        self.description_input = discord.ui.TextInput(
            label="Descrição",
            style=discord.TextStyle.paragraph,
            default=coupon.description or "",
            required=False,
            max_length=500,
        )
        self.emoji_input = discord.ui.TextInput(
            label="Emoji", default=coupon.emoji or "", required=False, max_length=64
        )
        self.add_item(self.code_input)
        self.add_item(self.description_input)
        self.add_item(self.emoji_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        try:
            coupon = await bot.coupon_service.update_coupon(
                self.coupon.id,
                code=str(self.code_input.value),
                description=str(self.description_input.value).strip() or None,
                emoji=str(self.emoji_input.value).strip() or None,
            )
        except CouponError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await _audit_coupon(interaction, coupon, "Cupom editado", campo="Informações")
        await _render_coupon_edit(interaction, coupon)


class _DiscountTypeSelect(discord.ui.Select[Any]):
    def __init__(self, coupon: DiscountCoupon) -> None:
        options = [
            discord.SelectOption(
                label=label, value=discount_type.value, default=coupon.discount_type == discount_type
            )
            for discount_type, label in _DISCOUNT_TYPE_LABELS.items()
        ]
        super().__init__(placeholder="Tipo de desconto...", options=options, min_values=1, max_values=1)
        self.coupon = coupon

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            _CouponValueModal(self.coupon, DiscountType(self.values[0]))
        )


class _CouponValueModal(discord.ui.Modal, title="Valor do desconto"):
    def __init__(self, coupon: DiscountCoupon, discount_type: DiscountType) -> None:
        super().__init__()
        self.coupon = coupon
        self.discount_type = discount_type
        if discount_type == DiscountType.PERCENTAGE:
            label = "Porcentagem (1 a 100)"
            default = str(coupon.discount_value) if coupon.discount_type == discount_type else ""
        else:
            label = "Valor fixo em reais (ex: 5.00)"
            default = (
                f"{coupon.discount_value / 100:.2f}"
                if coupon.discount_type == discount_type and coupon.discount_value
                else ""
            )
        self.value_input = discord.ui.TextInput(label=label, default=default, max_length=12)
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        raw = str(self.value_input.value).strip().replace(",", ".")
        try:
            value = int(raw) if self.discount_type == DiscountType.PERCENTAGE else round(
                float(raw) * 100
            )
        except ValueError:
            await interaction.response.send_message(
                "Valor inválido — use apenas números.", ephemeral=True
            )
            return
        try:
            coupon = await bot.coupon_service.set_discount(self.coupon.id, self.discount_type, value)
        except CouponError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await _audit_coupon(
            interaction, coupon, "Cupom editado", campo="Desconto", valor=format_discount(coupon)
        )
        await _render_coupon_edit(interaction, coupon)


class _CouponDatesModal(discord.ui.Modal, title="Validade do cupom"):
    def __init__(self, coupon: DiscountCoupon) -> None:
        super().__init__()
        self.coupon = coupon
        self.start_input = discord.ui.TextInput(
            label="Início (DD/MM/AAAA)",
            placeholder="Vazio = vale desde já",
            default=_format_date(coupon.starts_at) if coupon.starts_at else "",
            required=False,
            max_length=10,
        )
        self.end_input = discord.ui.TextInput(
            label="Expira em (DD/MM/AAAA)",
            placeholder="Vazio = sem expiração",
            default=_format_date(coupon.expires_at) if coupon.expires_at else "",
            required=False,
            max_length=10,
        )
        self.add_item(self.start_input)
        self.add_item(self.end_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        try:
            starts_at = _parse_date(str(self.start_input.value))
            expires_at = _parse_date(str(self.end_input.value))
        except ValueError:
            await interaction.response.send_message(
                "Data inválida — use o formato DD/MM/AAAA (ex: 31/12/2026).", ephemeral=True
            )
            return
        if starts_at is not None and expires_at is not None and expires_at < starts_at:
            await interaction.response.send_message(
                "A data de expiração não pode ser anterior à data de início.", ephemeral=True
            )
            return
        coupon = await bot.coupon_service.update_coupon(
            self.coupon.id, starts_at=starts_at, expires_at=expires_at
        )
        await _audit_coupon(
            interaction,
            coupon,
            "Cupom editado",
            campo="Validade",
            inicio=_format_date(starts_at),
            fim=_format_date(expires_at),
        )
        await _render_coupon_edit(interaction, coupon)


class _CouponLimitsModal(discord.ui.Modal, title="Limites de uso"):
    def __init__(self, coupon: DiscountCoupon) -> None:
        super().__init__()
        self.coupon = coupon
        self.global_input = discord.ui.TextInput(
            label="Limite global de usos",
            placeholder="Vazio = ilimitado (∞)",
            default=str(coupon.max_global_uses) if coupon.max_global_uses is not None else "",
            required=False,
            max_length=8,
        )
        self.per_user_input = discord.ui.TextInput(
            label="Limite por usuário",
            placeholder="Vazio = ilimitado (∞)",
            default=str(coupon.max_uses_per_user) if coupon.max_uses_per_user is not None else "",
            required=False,
            max_length=8,
        )
        self.add_item(self.global_input)
        self.add_item(self.per_user_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        try:
            max_global = _parse_optional_int(str(self.global_input.value))
            max_per_user = _parse_optional_int(str(self.per_user_input.value))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        coupon = await bot.coupon_service.update_coupon(
            self.coupon.id, max_global_uses=max_global, max_uses_per_user=max_per_user
        )
        await _audit_coupon(
            interaction,
            coupon,
            "Cupom editado",
            campo="Limites",
            global_=max_global if max_global is not None else "∞",
            por_usuario=max_per_user if max_per_user is not None else "∞",
        )
        await _render_coupon_edit(interaction, coupon)


# --- selects/pickers -------------------------------------------------------


class _CouponPlansSelect(discord.ui.Select[Any]):
    """Nenhuma opção marcada = cupom vale pra TODOS os planos (convenção da
    tabela discount_coupon_plans: zero linhas = sem restrição)."""

    def __init__(
        self, coupon: DiscountCoupon, plans: list[Plan], selected: list[uuid.UUID]
    ) -> None:
        chosen = set(selected)
        options = [
            discord.SelectOption(
                label=f"{plan.emoji or ''} {plan.name}".strip()[:100],
                value=str(plan.id),
                default=plan.id in chosen,
            )
            for plan in plans
        ][:25]
        super().__init__(
            placeholder="Planos válidos (nenhum = todos)...",
            options=options,
            min_values=0,
            max_values=len(options),
        )
        self.coupon = coupon

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        plan_ids = [uuid.UUID(value) for value in self.values]
        await bot.coupon_service.set_allowed_plans(self.coupon.id, plan_ids)
        await _audit_coupon(
            interaction, self.coupon, "Cupom editado", campo="Planos válidos", total=len(plan_ids)
        )
        coupon = await _load_coupon(interaction, self.coupon.id)
        if coupon is None:
            return
        await _render_coupon_edit(interaction, coupon)


class _CouponCyclesSelect(discord.ui.Select[Any]):
    def __init__(self, coupon: DiscountCoupon) -> None:
        chosen = set(coupon.billing_cycles or [])
        options = [
            discord.SelectOption(label=label, value=cycle.value, default=cycle.value in chosen)
            for cycle, label in _CYCLE_LABELS.items()
        ]
        super().__init__(
            placeholder="Modalidades (nenhuma = todas)...",
            options=options,
            min_values=0,
            max_values=len(options),
        )
        self.coupon = coupon

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        coupon = await bot.coupon_service.update_coupon(
            self.coupon.id, billing_cycles=list(self.values)
        )
        await _audit_coupon(
            interaction, coupon, "Cupom editado", campo="Modalidades", valor=list(self.values)
        )
        await _render_coupon_edit(interaction, coupon)


class _CouponRolePicker(discord.ui.RoleSelect):
    def __init__(self, coupon: DiscountCoupon) -> None:
        super().__init__(placeholder="Cargo obrigatório para usar o cupom", min_values=1, max_values=1)
        self.coupon = coupon

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        coupon = await bot.coupon_service.update_coupon(
            self.coupon.id, required_role_id=self.values[0].id
        )
        await _audit_coupon(
            interaction, coupon, "Cupom editado", campo="Cargo obrigatório", valor=self.values[0].id
        )
        await _render_coupon_edit(interaction, coupon)


class _ClearRequiredRoleButton(discord.ui.Button[Any]):
    def __init__(self, coupon: DiscountCoupon) -> None:
        super().__init__(label="🚫 Remover exigência", style=discord.ButtonStyle.secondary)
        self.coupon = coupon

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        coupon = await bot.coupon_service.update_coupon(self.coupon.id, required_role_id=None)
        await _audit_coupon(interaction, coupon, "Cupom editado", campo="Cargo obrigatório", valor=None)
        await _render_coupon_edit(interaction, coupon)


# --- estatisticas ----------------------------------------------------------


def coupon_stats_embed(stats: CouponStats, currency: str = "BRL") -> discord.Embed:
    coupon = stats.coupon
    embed = discord.Embed(
        title=f"📊 {coupon.emoji or '🎟️'} {coupon.code}",
        color=EMBED_COLOR_PURPLE,
    )
    embed.add_field(name="Código", value=coupon.code)
    embed.add_field(name="Status", value="✅ Ativo" if coupon.active else "🚫 Inativo")
    embed.add_field(name="Desconto", value=format_discount(coupon, currency=currency))
    embed.add_field(name="Criado em", value=_format_date(coupon.created_at))
    embed.add_field(name="Expira em", value=_format_date(coupon.expires_at))
    embed.add_field(
        name="Utilizações",
        value=(
            f"{stats.total_redemptions}/"
            f"{stats.max_global_uses if stats.max_global_uses is not None else '∞'}"
        ),
    )
    embed.add_field(name="Receita gerada", value=f"{currency} {stats.revenue_cents / 100:.2f}")
    embed.add_field(name="Total descontado", value=f"{currency} {stats.discounted_cents / 100:.2f}")
    embed.add_field(
        name="Última utilização",
        value=(
            f"<t:{int(stats.last_used_at.timestamp())}:R>"
            if stats.last_used_at is not None
            else "—"
        ),
    )
    return embed


class _CouponStatsSelect(discord.ui.Select[Any]):
    def __init__(self, coupons: list[DiscountCoupon]) -> None:
        options = [
            discord.SelectOption(label=f"{coupon.emoji or '🎟️'} {coupon.code}"[:100], value=str(coupon.id))
            for coupon in coupons
        ][:25]
        super().__init__(placeholder="Cupom...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        coupon = await _load_coupon(interaction, uuid.UUID(self.values[0]))
        if coupon is None:
            return
        stats = await bot.coupon_service.coupon_stats(coupon.id)
        if stats is None:
            await interaction.response.send_message("Cupom não encontrado.", ephemeral=True)
            return
        view = SafeView(timeout=300)
        view.add_item(_BackToCouponsMenuButton())
        await interaction.response.edit_message(
            content=None, embed=coupon_stats_embed(stats), view=view
        )
