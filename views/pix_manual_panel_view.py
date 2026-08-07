from __future__ import annotations

import base64
import io
import uuid
from typing import TYPE_CHECKING, Any

import discord

from database.models.pix_manual_settings import PIX_KEY_TYPES, PixManualSettings
from utils.checks import member_is_admin
from utils.pix_payload import build_pix_payload, generate_qr_base64
from utils.pix_validation import PixKeyValidationError, validate_pix_key
from views.settings_panel import DomainSettingsView, FieldKind, SettingsField, build_domain_embed

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_EXPIRATION_CHOICES = [
    ("30", "30 minutos"),
    ("60", "1 hora"),
    ("360", "6 horas"),
    ("1440", "24 horas"),
    ("2880", "48 horas"),
]


def _validate_pix_key_type_change(settings: PixManualSettings, new_type: str) -> str:
    """Ao trocar o TIPO da chave, revalida a chave JÁ SALVA contra o novo
    tipo — sem isso seria possível deixar pix_key_type="cpf" com uma chave
    que na verdade é um e-mail (o payload EMV geraria um QR com chave
    inválida pro tipo declarado, e o pagador tomaria erro no banco)."""
    if settings.pix_key:
        validate_pix_key(new_type, settings.pix_key)
    return new_type


def _validate_pix_key_change(settings: PixManualSettings, raw_key: str) -> str:
    return validate_pix_key(settings.pix_key_type, raw_key)


PIX_MANUAL_FIELDS = [
    SettingsField(
        "pix_key_type", "Tipo da chave PIX", FieldKind.CHOICE, PixManualSettings, choices=PIX_KEY_TYPES,
        validator=_validate_pix_key_type_change,
    ),
    SettingsField("pix_key", "Chave PIX", FieldKind.TEXT, PixManualSettings, validator=_validate_pix_key_change),
    SettingsField("receiver_name", "Nome do recebedor", FieldKind.TEXT, PixManualSettings),
    SettingsField("receiver_city", "Cidade", FieldKind.TEXT, PixManualSettings),
    SettingsField("bank_name", "Banco", FieldKind.TEXT, PixManualSettings),
    SettingsField("buyer_message", "Mensagem exibida ao comprador", FieldKind.TEXT, PixManualSettings),
    SettingsField(
        "expiration_minutes", "Expiração do pedido", FieldKind.CHOICE, PixManualSettings,
        choices=_EXPIRATION_CHOICES,
    ),
    SettingsField("send_qr_code", "Enviar QR Code", FieldKind.BOOL, PixManualSettings),
    SettingsField("send_copy_paste", "Enviar PIX Copia e Cola", FieldKind.BOOL, PixManualSettings),
    SettingsField("manual_approval", "Aprovação Manual", FieldKind.BOOL, PixManualSettings),
]


class _TestPixButton(discord.ui.Button[Any]):
    """Gera um QR/copia-e-cola FICTICIO (R$ 1,00) com a chave configurada,
    visivel so pra quem clicou — nenhum PaymentHistory e criado."""

    def __init__(self) -> None:
        super().__init__(label="🧪 Testar Configuração PIX", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        if not await member_is_admin(interaction):
            await interaction.response.send_message(
                "Apenas admins podem testar a configuração do PIX.", ephemeral=True
            )
            return
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        settings = await bot.payment_service.get_pix_manual_settings(interaction.guild_id)

        # validacao campo a campo, com mensagem especifica de qual campo esta
        # faltando/invalido — em vez de uma unica checagem generica que nao
        # diz ao admin o que exatamente precisa corrigir.
        missing = []
        if not settings.pix_key_type:
            missing.append("**Tipo da chave PIX**")
        if not settings.pix_key:
            missing.append("**Chave PIX**")
        if not settings.receiver_name:
            missing.append("**Nome do recebedor**")
        if missing:
            await interaction.response.send_message(
                "Configure " + ", ".join(missing) + " antes de testar.",
                ephemeral=True,
            )
            return

        try:
            normalized_key = validate_pix_key(settings.pix_key_type, settings.pix_key or "")
        except PixKeyValidationError as exc:
            await interaction.response.send_message(
                f"❌ A chave PIX salva não é válida para o tipo configurado: {exc}\n"
                "Abra **Chave PIX** ou **Tipo da chave PIX** e corrija antes de testar.",
                ephemeral=True,
            )
            return

        try:
            payload = build_pix_payload(
                pix_key=normalized_key,
                receiver_name=settings.receiver_name or "",
                receiver_city=settings.receiver_city,
                amount_cents=100,
                txid=f"TESTE{uuid.uuid4().hex[:8]}",
            )
            qr_b64 = generate_qr_base64(payload)
        except (ValueError, TypeError) as exc:
            await interaction.response.send_message(
                f"❌ Não foi possível gerar o payload/QR de teste: {exc}", ephemeral=True
            )
            return

        file = discord.File(io.BytesIO(base64.b64decode(qr_b64)), filename="pix_teste.png")

        embed = discord.Embed(
            title="🧪 Teste de configuração PIX",
            description="QR e código fictícios (R$ 1,00) — nenhum pagamento real foi criado.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Código PIX (copia e cola)", value=f"```{payload}```", inline=False)
        embed.set_image(url="attachment://pix_teste.png")
        await interaction.response.send_message(embed=embed, file=file, ephemeral=True)


class PixManualSettingsView(DomainSettingsView):
    """DomainSettingsView generico + botao de teste — precisa sobrescrever
    render() pra reconstruir ESTA subclasse (senao o botao de teste some depois
    do primeiro campo editado, porque o render() da base reconstroi um
    DomainSettingsView puro)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.add_item(_TestPixButton())

    async def render(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        settings = await self.get_settings(interaction.guild_id)
        await interaction.response.edit_message(
            content=None,
            embed=build_domain_embed(self.title, self.fields, settings),
            view=PixManualSettingsView(
                title=self.title,
                fields=self.fields,
                get_settings=self.get_settings,
                update_settings=self.update_settings,
                on_back=self.on_back,
            ),
        )


async def render_pix_manual_menu(interaction: discord.Interaction) -> None:
    from views.monetization_panel_view import _back_to_monetization_menu

    assert interaction.guild_id is not None
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]

    async def get_settings(guild_id: int) -> PixManualSettings:
        return await bot.payment_service.get_pix_manual_settings(guild_id)

    view = PixManualSettingsView(
        title="🧾 Monetização — PIX Manual",
        fields=PIX_MANUAL_FIELDS,
        get_settings=get_settings,
        update_settings=bot.payment_service.update_pix_manual_settings,
        on_back=_back_to_monetization_menu,
    )
    settings = await get_settings(interaction.guild_id)
    await interaction.response.edit_message(
        content=(
            "A chave PIX não é um segredo (ela precisa ser mostrada ao comprador), mas só "
            "administradores conseguem ver/editar esta tela."
        ),
        embed=build_domain_embed(view.title, view.fields, settings),
        view=view,
    )
