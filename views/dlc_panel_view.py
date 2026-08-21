from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import discord

from database.models.product import Product
from services.dlc_service import DlcError
from utils.constants import EMBED_COLOR_DEFAULT, EMBED_COLOR_WARNING
from views.base_view import SafeView

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_MAX_SLUG_LENGTH = 80


def _slugify(raw: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    return slug[:_MAX_SLUG_LENGTH] or "dlc"


def _parse_reais(raw: str) -> int | None:
    raw = raw.strip().replace(",", ".")
    if not raw:
        return None
    return round(float(raw) * 100)


def dlc_list_embed(dlcs: list[Product]) -> discord.Embed:
    embed = discord.Embed(title="🎮 DLCs cadastradas", color=EMBED_COLOR_DEFAULT)
    if not dlcs:
        embed.description = "Nenhuma DLC cadastrada ainda. Use o menu abaixo pra criar a primeira."
    else:
        for product in dlcs:
            status = "✅ Ativa" if product.is_active else "🚫 Inativa"
            kind = f"💰 {product.currency} {product.price_amount / 100:.2f}" if product.price_amount else "🎁 Gratuita"
            embed.add_field(name=product.name, value=f"{kind} · {status}", inline=False)
    return embed


class DlcListView(SafeView):
    def __init__(self, dlcs: list[Product]) -> None:
        super().__init__(timeout=300)
        self.dlcs = dlcs
        if dlcs:
            self.add_item(_DlcSelect(dlcs))
        self.add_item(_CreateFreeDlcButton())
        self.add_item(_CreatePaidDlcButton())
        self.add_item(_BackToMonetizationMenuButton())


class _DlcSelect(discord.ui.Select[Any]):
    def __init__(self, dlcs: list[Product]) -> None:
        options = [discord.SelectOption(label=p.name, value=str(p.id)) for p in dlcs][:25]
        super().__init__(placeholder="Selecione uma DLC pra editar...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        product = await bot.dlc_service.get(uuid.UUID(self.values[0]))
        if product is None:
            await interaction.followup.send("DLC não encontrada.", ephemeral=True)
            return
        await interaction.edit_original_response(
            content=None, embed=await _dlc_edit_embed(bot, product), view=DlcEditView(product)
        )


class _CreateFreeDlcButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(label="🎁 Criar DLC Gratuita", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(_CreateDlcModal(paid=False))


class _CreatePaidDlcButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(label="💰 Criar DLC Paga", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(_CreateDlcModal(paid=True))


class _CreateDlcModal(discord.ui.Modal):
    def __init__(self, *, paid: bool) -> None:
        super().__init__(title="Criar DLC paga" if paid else "Criar DLC gratuita")
        self.paid = paid
        self.name_input = discord.ui.TextInput(
            label="Nome da DLC", placeholder="Ex: The Empress, The Devil...", max_length=150
        )
        self.description_input = discord.ui.TextInput(
            label="Descrição (aparece na loja)",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
        )
        self.add_item(self.name_input)
        self.add_item(self.description_input)
        if paid:
            self.price_input = discord.ui.TextInput(label="Preço (ex: 14.90)", max_length=12)
            self.add_item(self.price_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = str(self.name_input.value).strip()
        description = str(self.description_input.value).strip() or None
        slug = _slugify(name)

        if not self.paid:
            # DLC gratuita nunca pede cargo manual — libera sozinha pra quem
            # tem o cargo Verificado da guild (ver DlcService.create_free).
            assert interaction.guild_id is not None
            bot: LimerenceBot = interaction.client  # type: ignore[assignment]
            try:
                product = await bot.dlc_service.create_free(
                    guild_id=interaction.guild_id, name=name, slug=slug, description=description,
                    executor=interaction.user,
                )
            except DlcError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
            await interaction.response.edit_message(
                content=None, embed=await _dlc_edit_embed(bot, product), view=DlcEditView(product)
            )
            return

        try:
            price_amount = _parse_reais(str(self.price_input.value))
        except ValueError:
            await interaction.response.send_message("Preço inválido — use números (ex: 14.90).", ephemeral=True)
            return
        if not price_amount:
            await interaction.response.send_message("DLC paga precisa de um preço maior que zero.", ephemeral=True)
            return

        await interaction.response.edit_message(
            content="Selecione o cargo Discord desta DLC:",
            embed=None,
            view=_PendingDlcRolePicker(
                name=name, slug=slug, description=description, price_amount=price_amount
            ),
        )


class _PendingDlcRolePicker(SafeView):
    """Segundo passo da criação — Modal não pode conter RoleSelect, então o
    cargo é escolhido numa view separada guardando os campos já digitados."""

    def __init__(self, *, name: str, slug: str, description: str | None, price_amount: int | None) -> None:
        super().__init__(timeout=120)
        self.add_item(_PendingDlcRoleSelect(name=name, slug=slug, description=description, price_amount=price_amount))


class _PendingDlcRoleSelect(discord.ui.RoleSelect):
    def __init__(self, *, name: str, slug: str, description: str | None, price_amount: int | None) -> None:
        super().__init__(placeholder="Cargo necessário para acessar esta DLC", min_values=1, max_values=1)
        self.name = name
        self.slug = slug
        self.description = description
        self.price_amount = price_amount

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        role_id = self.values[0].id
        try:
            if self.price_amount:
                product, _plan = await bot.dlc_service.create_paid(
                    guild_id=interaction.guild_id,
                    name=self.name,
                    slug=self.slug,
                    description=self.description,
                    price_amount=self.price_amount,
                    role_id=role_id,
                    executor=interaction.user,
                )
            else:
                product = await bot.dlc_service.create_free(
                    guild_id=interaction.guild_id,
                    name=self.name,
                    slug=self.slug,
                    description=self.description,
                    required_role_id=role_id,
                    executor=interaction.user,
                )
        except DlcError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.edit_original_response(
            content=None, embed=await _dlc_edit_embed(bot, product), view=DlcEditView(product)
        )


class _BackToMonetizationMenuButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        await _back_to_monetization_menu(interaction)


async def _back_to_monetization_menu(interaction: discord.Interaction) -> None:
    from views.monetization_panel_view import MonetizationMenuView, monetization_menu_embed

    await interaction.response.edit_message(
        content=None, embed=monetization_menu_embed(), view=MonetizationMenuView()
    )


async def _dlc_edit_embed(bot: LimerenceBot, product: Product) -> discord.Embed:
    color = EMBED_COLOR_DEFAULT if product.is_active else EMBED_COLOR_WARNING
    embed = discord.Embed(title=product.name, color=color)
    embed.description = product.description or "*(sem descrição)*"
    embed.add_field(name="Status", value="✅ Ativa" if product.is_active else "🚫 Inativa")
    embed.add_field(name="Slug", value=product.slug)

    plan = await bot.dlc_service.get_purchase_plan(product.id)
    if plan is not None:
        embed.add_field(name="Tipo", value="💰 Paga")
        embed.add_field(name="Preço", value=f"{plan.currency} {plan.price_one_time / 100:.2f}")
        embed.add_field(name="Cargo", value=f"<@&{plan.role_id}>" if plan.role_id else "— (compra não libera cargo)")
    else:
        embed.add_field(name="Tipo", value="🎁 Gratuita")
        embed.add_field(
            name="Cargo necessário",
            value=f"<@&{product.required_role_id}>" if product.required_role_id else "— (nenhum jogador tem acesso)",
        )
    return embed


class DlcEditView(SafeView):
    def __init__(self, product: Product) -> None:
        super().__init__(timeout=300)
        self.product = product

    @discord.ui.button(label="✏️ Info", style=discord.ButtonStyle.primary, row=0)
    async def info_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(_DlcInfoModal(self.product))

    @discord.ui.button(label="💲 Preço", style=discord.ButtonStyle.primary, row=0)
    async def price_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        plan = await bot.dlc_service.get_purchase_plan(self.product.id)
        if plan is None:
            await interaction.response.send_message(
                "Esta DLC é gratuita — preço não se aplica. Crie uma nova DLC paga se precisar cobrar por ela.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(_DlcPriceModal(self.product, plan.price_one_time))

    @discord.ui.button(label="🎭 Cargo", style=discord.ButtonStyle.secondary, row=1)
    async def role_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        if await bot.dlc_service.get_purchase_plan(self.product.id) is None:
            await interaction.response.send_message(
                "DLC gratuita libera automaticamente pra quem tem o cargo Verificado — "
                "não dá pra trocar manualmente.",
                ephemeral=True,
            )
            return
        view = SafeView(timeout=120)
        view.add_item(_EditRolePicker(self.product))
        await interaction.response.edit_message(
            content="Selecione o cargo necessário pra esta DLC:", embed=None, view=view
        )

    @discord.ui.button(label="✅ Ativo/Inativo", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_active(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        product = await bot.dlc_service.toggle_active(
            self.product.id, is_active=not self.product.is_active, executor=interaction.user
        )
        await _render_dlc_edit(interaction, product)

    @discord.ui.button(label="🗑️ Excluir", style=discord.ButtonStyle.danger, row=1)
    async def delete_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        view = SafeView(timeout=60)
        view.add_item(_ConfirmDeleteButton(self.product))
        view.add_item(_BackToDlcEditButton(self.product))
        await interaction.response.edit_message(
            content=(
                f"Tem certeza que deseja excluir **{self.product.name}**? "
                "Compras/licenças existentes são mantidas no histórico — a DLC só some do catálogo."
            ),
            embed=None,
            view=view,
        )

    @discord.ui.button(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        dlcs = await bot.dlc_service.list_dlcs()
        await interaction.edit_original_response(content=None, embed=dlc_list_embed(dlcs), view=DlcListView(dlcs))


async def _render_dlc_edit(interaction: discord.Interaction, product: Product) -> None:
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    embed = await _dlc_edit_embed(bot, product)
    if interaction.response.is_done():
        await interaction.edit_original_response(embed=embed, view=DlcEditView(product))
    else:
        await interaction.response.edit_message(embed=embed, view=DlcEditView(product))


class _BackToDlcEditButton(discord.ui.Button[Any]):
    def __init__(self, product: Product) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary)
        self.product = product

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await _render_dlc_edit(interaction, self.product)


class _ConfirmDeleteButton(discord.ui.Button[Any]):
    def __init__(self, product: Product) -> None:
        super().__init__(label="Confirmar exclusão", style=discord.ButtonStyle.danger)
        self.product = product

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        await bot.dlc_service.disable(self.product.id, executor=interaction.user)
        dlcs = await bot.dlc_service.list_dlcs()
        await interaction.edit_original_response(content=None, embed=dlc_list_embed(dlcs), view=DlcListView(dlcs))


class _EditRolePicker(discord.ui.RoleSelect):
    def __init__(self, product: Product) -> None:
        super().__init__(placeholder="Cargo necessário para acessar esta DLC", min_values=1, max_values=1)
        self.product = product

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        try:
            product = await bot.dlc_service.update_role(
                self.product.id, role_id=self.values[0].id, guild_id=interaction.guild_id, executor=interaction.user
            )
        except DlcError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await _render_dlc_edit(interaction, product)


class _DlcInfoModal(discord.ui.Modal, title="Editar informações"):
    def __init__(self, product: Product) -> None:
        super().__init__()
        self.product = product
        self.name_input = discord.ui.TextInput(label="Nome", default=product.name, max_length=150)
        self.description_input = discord.ui.TextInput(
            label="Descrição (aparece na loja)",
            style=discord.TextStyle.paragraph,
            default=product.description or "",
            required=False,
            max_length=1000,
        )
        self.add_item(self.name_input)
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        try:
            product = await bot.dlc_service.update_info(
                self.product.id,
                name=str(self.name_input.value).strip(),
                description=str(self.description_input.value).strip() or None,
                executor=interaction.user,
            )
        except DlcError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await _render_dlc_edit(interaction, product)


class _DlcPriceModal(discord.ui.Modal, title="Editar preço"):
    def __init__(self, product: Product, current_price: int) -> None:
        super().__init__()
        self.product = product
        self.price_input = discord.ui.TextInput(
            label="Preço (ex: 14.90)", default=f"{current_price / 100:.2f}", max_length=12
        )
        self.add_item(self.price_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        try:
            price_amount = _parse_reais(str(self.price_input.value))
        except ValueError:
            await interaction.response.send_message("Preço inválido — use números (ex: 14.90).", ephemeral=True)
            return
        if not price_amount:
            await interaction.response.send_message("Preço tem que ser maior que zero.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            product = await bot.dlc_service.update_price(
                self.product.id, price_amount=price_amount, executor=interaction.user
            )
        except DlcError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await _render_dlc_edit(interaction, product)
