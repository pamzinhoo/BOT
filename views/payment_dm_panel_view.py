from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import discord
from views.base_view import SafeView

from database.models.payment_dm_settings import PaymentDmSettings
from utils.constants import EMBED_COLOR_DANGER, EMBED_COLOR_DEFAULT, EMBED_COLOR_SUCCESS
from views.embeds import PAYMENT_DM_DEFAULTS

if TYPE_CHECKING:
    from core.bot import LimerenceBot


def _valid_url(raw: str) -> bool:
    return raw.startswith("http://") or raw.startswith("https://")


def _fake_placeholders(member: discord.Member, *, approved: bool) -> dict[str, str]:
    return {
        "{user}": member.mention,
        "{mention}": member.mention,
        "{plan}": "Plano Exemplo",
        "{plan_name}": "Plano Exemplo",
        "{price}": "BRL 19.90",
        "{plan_price}": "BRL 19.90",
        "{payment_id}": "00000000-0000-0000-0000-000000000000",
        "{guild}": member.guild.name,
        "{server_name}": member.guild.name,
        "{staff}": member.mention,
        "{staff_mention}": member.mention,
        "{status}": "Aprovado" if approved else "Rejeitado",
        "{date}": datetime.now(UTC).strftime("%d/%m/%Y"),
    }


def _render_preview(template: str, fake: dict[str, str]) -> str:
    result = template
    for placeholder, value in fake.items():
        result = result.replace(placeholder, value)
    return result


def _preview_embed(settings: PaymentDmSettings, *, approved: bool, member: discord.Member) -> discord.Embed:
    """Mesma logica de renderizacao de views.embeds.payment_dm_embed, mas com
    dados FICTICIOS no lugar de member/plan/payment reais — usada tanto na
    pre-visualizacao automatica do painel quanto no botao de teste."""
    defaults = PAYMENT_DM_DEFAULTS[approved]
    prefix = "approved" if approved else "rejected"
    fake = _fake_placeholders(member, approved=approved)

    def _field(name: str) -> str | None:
        return getattr(settings, f"{prefix}_embed_{name}")

    title = _render_preview(_field("title") or defaults["title"], fake)
    description = _render_preview(_field("description") or defaults["description"], fake)
    color_value = _field("color")
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color(color_value) if color_value is not None else (
            EMBED_COLOR_SUCCESS if approved else EMBED_COLOR_DANGER
        ),
    )
    footer = _field("footer")
    if footer:
        embed.set_footer(text=_render_preview(footer, fake))
    thumbnail = _field("thumbnail_url")
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    image = _field("image_url")
    if image:
        embed.set_image(url=image)
    return embed


def _menu_embed(settings: PaymentDmSettings) -> discord.Embed:
    embed = discord.Embed(
        title="📨 Monetização — Mensagens ao Comprador",
        description=(
            "DM enviada automaticamente ao comprador quando um staff aprova ou rejeita um "
            "pagamento. Placeholders: `{user}` `{plan}` `{price}` `{payment_id}` `{guild}` "
            "`{staff}` `{status}` `{date}`."
        ),
        color=EMBED_COLOR_DEFAULT,
    )
    embed.add_field(
        name="✅ Pagamento Aprovado", value="Ativado" if settings.approved_enabled else "Desativado"
    )
    embed.add_field(
        name="❌ Pagamento Rejeitado", value="Ativado" if settings.rejected_enabled else "Desativado"
    )
    return embed


async def render_payment_dm_menu(interaction: discord.Interaction) -> None:
    assert interaction.guild_id is not None
    bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
    settings = await bot.payment_service.get_payment_dm_settings(interaction.guild_id)
    await interaction.response.edit_message(content=None, embed=_menu_embed(settings), view=PaymentDmMenuView())


class PaymentDmMenuView(SafeView):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="✅ Aprovado", style=discord.ButtonStyle.success)
    async def approved_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await _render_state_editor(interaction, approved=True)

    @discord.ui.button(label="❌ Rejeitado", style=discord.ButtonStyle.danger)
    async def rejected_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await _render_state_editor(interaction, approved=False)

    @discord.ui.button(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from views.monetization_panel_view import _back_to_monetization_menu

        await _back_to_monetization_menu(interaction)


async def _render_state_editor(interaction: discord.Interaction, *, approved: bool) -> None:
    assert interaction.guild_id is not None
    if not isinstance(interaction.user, discord.Member):
        return
    bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
    settings = await bot.payment_service.get_payment_dm_settings(interaction.guild_id)
    label = "✅ Pagamento Aprovado" if approved else "❌ Pagamento Rejeitado"
    header = discord.Embed(
        title=f"📨 {label}",
        description="Pré-visualização com os valores atuais (texto padrão se algum campo estiver vazio):",
        color=EMBED_COLOR_SUCCESS if approved else EMBED_COLOR_DANGER,
    )
    preview = _preview_embed(settings, approved=approved, member=interaction.user)
    await interaction.response.edit_message(content=None, embeds=[header, preview], view=_StateEditorView(approved))


class _StateEditorView(SafeView):
    def __init__(self, approved: bool) -> None:
        super().__init__(timeout=300)
        self.approved = approved

    @discord.ui.button(label="📝 Texto e cor", style=discord.ButtonStyle.primary)
    async def text_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        assert interaction.guild_id is not None
        bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
        settings = await bot.payment_service.get_payment_dm_settings(interaction.guild_id)
        await interaction.response.send_modal(_TextModal(self.approved, settings))

    @discord.ui.button(label="🖼️ Imagem e thumbnail", style=discord.ButtonStyle.primary)
    async def images_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        assert interaction.guild_id is not None
        bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
        settings = await bot.payment_service.get_payment_dm_settings(interaction.guild_id)
        await interaction.response.send_modal(_ImagesModal(self.approved, settings))

    @discord.ui.button(label="🔛 Ativar/Desativar", style=discord.ButtonStyle.secondary)
    async def toggle_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        assert interaction.guild_id is not None
        bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
        settings = await bot.payment_service.get_payment_dm_settings(interaction.guild_id)
        key = "approved_enabled" if self.approved else "rejected_enabled"
        await bot.payment_service.update_payment_dm_settings(
            interaction.guild_id, **{key: not getattr(settings, key)}
        )
        await _render_state_editor(interaction, approved=self.approved)

    @discord.ui.button(label="📨 Enviar Mensagem de Teste", style=discord.ButtonStyle.secondary, row=1)
    async def test_send_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        assert interaction.guild_id is not None
        if not isinstance(interaction.user, discord.Member):
            return
        bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
        settings = await bot.payment_service.get_payment_dm_settings(interaction.guild_id)
        embed = _preview_embed(settings, approved=self.approved, member=interaction.user)
        try:
            await interaction.user.send(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message(
                "Não consegui te mandar DM — verifique se suas mensagens privadas estão abertas.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            await interaction.response.send_message("Falha ao enviar a DM de teste.", ephemeral=True)
            return
        await interaction.response.send_message("📨 Mensagem de teste enviada por DM.", ephemeral=True)

    @discord.ui.button(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await render_payment_dm_menu(interaction)


class _TextModal(discord.ui.Modal, title="Embed — texto e cor"):
    def __init__(self, approved: bool, settings: PaymentDmSettings) -> None:
        super().__init__()
        self.approved = approved
        prefix = "approved" if approved else "rejected"
        self.title_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Título", default=getattr(settings, f"{prefix}_embed_title") or "",
            required=False, max_length=256,
        )
        self.description_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Mensagem", style=discord.TextStyle.paragraph,
            default=getattr(settings, f"{prefix}_embed_description") or "",
            required=False, max_length=2000,
        )
        color_raw = getattr(settings, f"{prefix}_embed_color")
        self.color_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Cor em hexadecimal", placeholder="Ex: #57F287 (vazio = cor padrão)",
            default=f"#{color_raw:06X}" if color_raw is not None else "",
            required=False, max_length=7,
        )
        self.footer_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Rodapé", default=getattr(settings, f"{prefix}_embed_footer") or "",
            required=False, max_length=200,
        )
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.color_input)
        self.add_item(self.footer_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        raw_color = str(self.color_input.value).strip().lstrip("#")
        color: int | None = None
        if raw_color:
            try:
                color = int(raw_color, 16)
            except ValueError:
                await interaction.response.send_message(
                    "Cor inválida — use um hexadecimal (ex: #57F287).", ephemeral=True
                )
                return
        bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
        prefix = "approved" if self.approved else "rejected"
        await bot.payment_service.update_payment_dm_settings(
            interaction.guild_id,
            **{
                f"{prefix}_embed_title": str(self.title_input.value).strip() or None,
                f"{prefix}_embed_description": str(self.description_input.value).strip() or None,
                f"{prefix}_embed_color": color,
                f"{prefix}_embed_footer": str(self.footer_input.value).strip() or None,
            },
        )
        await _render_state_editor(interaction, approved=self.approved)


class _ImagesModal(discord.ui.Modal, title="Embed — imagens"):
    def __init__(self, approved: bool, settings: PaymentDmSettings) -> None:
        super().__init__()
        self.approved = approved
        prefix = "approved" if approved else "rejected"
        self.image_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="URL da imagem", placeholder="https://... (vazio = sem imagem)",
            default=getattr(settings, f"{prefix}_embed_image_url") or "",
            required=False, max_length=500,
        )
        self.thumb_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="URL da thumbnail", placeholder="https://... (vazio = sem thumbnail)",
            default=getattr(settings, f"{prefix}_embed_thumbnail_url") or "",
            required=False, max_length=500,
        )
        self.add_item(self.image_input)
        self.add_item(self.thumb_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        image = str(self.image_input.value).strip()
        thumb = str(self.thumb_input.value).strip()
        for raw in (image, thumb):
            if raw and not _valid_url(raw):
                await interaction.response.send_message(
                    "URL inválida — precisa começar com http:// ou https://.", ephemeral=True
                )
                return
        bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
        prefix = "approved" if self.approved else "rejected"
        await bot.payment_service.update_payment_dm_settings(
            interaction.guild_id,
            **{
                f"{prefix}_embed_image_url": image or None,
                f"{prefix}_embed_thumbnail_url": thumb or None,
            },
        )
        await _render_state_editor(interaction, approved=self.approved)
