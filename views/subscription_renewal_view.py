from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import discord

from database.models.subscription import SubscriptionStatus
from database.models.subscription_renewal import (
    SubscriptionMessageType,
    SubscriptionRenewalButtonKey,
    SubscriptionRenewalSettings,
)
from services.subscription_renewal_config_service import (
    CHECK_INTERVAL_CHOICES,
    DEFAULT_MESSAGES,
    GRACE_PERIOD_CHOICES,
)
from utils.constants import EMBED_COLOR_DEFAULT
from views.base_view import SafeView

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_CATEGORY_LABEL = "Renovação de Assinaturas"

_MESSAGE_TYPE_LABELS = {
    SubscriptionMessageType.REMINDER: "Lembrete",
    SubscriptionMessageType.LAST_REMINDER: "Último aviso",
    SubscriptionMessageType.EXPIRED: "Expiração",
    SubscriptionMessageType.RENEWED: "Renovada",
    SubscriptionMessageType.GRACE_PERIOD: "Período de carência",
}

_BUTTON_LABELS = {
    SubscriptionRenewalButtonKey.RENEW: "Renovar",
    SubscriptionRenewalButtonKey.VIEW_PLAN: "Ver Plano",
    SubscriptionRenewalButtonKey.OPEN_STORE: "Abrir Loja",
    SubscriptionRenewalButtonKey.CLOSE: "Fechar",
}

_PLACEHOLDER_HELP = (
    "{user} {mention} {server_name} {plan_name} {plan_emoji} {plan_price} {role_name} "
    "{renew_date} {expires_at} {days_left} {grace_days} {renew_link} {renew_command} "
    "{store_command} {subscription_id}"
)

_DELIVERY_LABELS = {
    (True, True): "DM + Canal",
    (True, False): "Somente DM",
    (False, True): "Somente Canal",
    (False, False): "Nenhum (desligado)",
}

PAGE_SIZE = 5


async def _log_change(
    interaction: discord.Interaction, config_name: str, old_value: str, new_value: str
) -> None:
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    assert interaction.guild_id is not None
    await bot.audit_log_service.record_config_change(
        guild_id=interaction.guild_id,
        actor_id=interaction.user.id,
        actor_name=str(interaction.user),
        config_category=_CATEGORY_LABEL,
        config_name=config_name,
        old_value=old_value,
        new_value=new_value,
    )


def _onoff(value: bool) -> str:
    return "✅ Ativado" if value else "❌ Desativado"


async def renewal_menu_embed(
    bot: LimerenceBot, guild_id: int, settings: SubscriptionRenewalSettings
) -> discord.Embed:
    days = await bot.subscription_renewal_config_service.list_reminder_days(guild_id)
    embed = discord.Embed(
        title="🔁 Renovação de Assinaturas",
        description=(
            "Avisos automáticos antes do vencimento, carência configurável e remoção "
            "automática de benefícios. Tudo por servidor, nada fixo."
        ),
        color=EMBED_COLOR_DEFAULT,
    )
    embed.add_field(name="Sistema", value=_onoff(settings.enabled))
    embed.add_field(
        name="Notificações",
        value=_DELIVERY_LABELS[(settings.notify_via_dm, settings.notify_via_channel)],
    )
    embed.add_field(
        name="Canal de Renovações",
        value=f"<#{settings.renewal_channel_id}>" if settings.renewal_channel_id else "—",
    )
    embed.add_field(name="Frequência", value=f"A cada {settings.check_interval_hours}h")
    embed.add_field(name="Carência", value=f"{settings.grace_period_days} dia(s)")
    embed.add_field(
        name="Avisos",
        value=(
            " · ".join(
                f"{'✅' if d.enabled else '🚫'} {d.days_before}d" for d in days
            )
            or "Nenhum aviso configurado"
        ),
        inline=False,
    )
    embed.add_field(
        name="Remoção automática",
        value=(
            f"Cargos: {_onoff(settings.remove_roles_on_expire)}\n"
            f"Benefícios: {_onoff(settings.remove_benefits_on_expire)}\n"
            f"Encerrar assinatura: {_onoff(settings.end_subscription_on_expire)}\n"
            f"DM ao remover: {_onoff(settings.send_dm_on_removal)}\n"
            f"Auditoria: {_onoff(settings.log_audit)}\n"
            f"Avisar durante carência: {_onoff(settings.continue_reminders_during_grace)}"
        ),
        inline=False,
    )
    return embed


async def render_renewal_menu(interaction: discord.Interaction) -> None:
    # Toda chamada dentro deste arquivo ja deferiza antes de chegar aqui, mas
    # views/monetization_panel_view.py (o botao de entrada) chama direto sem
    # deferizar e nao ha como editar aquele arquivo — entao deferizamos aqui
    # tambem, com guard pra nao duplicar quando o chamador ja deferizou.
    if not interaction.response.is_done():
        await interaction.response.defer()
    assert interaction.guild_id is not None
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    settings = await bot.subscription_renewal_config_service.get_settings(interaction.guild_id)
    embed = await renewal_menu_embed(bot, interaction.guild_id, settings)
    view = SubscriptionRenewalMenuView(settings)
    await interaction.edit_original_response(content=None, embed=embed, view=view)


class SubscriptionRenewalMenuView(SafeView):
    """Tela principal de /config painel > Monetização > Renovação de Assinaturas."""

    def __init__(self, settings: SubscriptionRenewalSettings) -> None:
        super().__init__(timeout=300)
        self.settings = settings
        self.toggle_enabled.label = (
            "🚫 Desativar renovações" if settings.enabled else "✅ Ativar renovações"
        )

    @discord.ui.button(label="✅ Ativar renovações", style=discord.ButtonStyle.success, row=0)
    async def toggle_enabled(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        before = self.settings.enabled
        await bot.subscription_renewal_config_service.update_settings(
            interaction.guild_id, enabled=not before
        )
        await _log_change(interaction, "Renovações ativas", _onoff(before), _onoff(not before))
        await render_renewal_menu(interaction)

    @discord.ui.button(label="⏰ Avisos", style=discord.ButtonStyle.primary, row=0)
    async def days_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await interaction.response.defer()
        await render_days_menu(interaction)

    @discord.ui.button(label="📢 Canais", style=discord.ButtonStyle.primary, row=0)
    async def channels_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        view = SafeView(timeout=180)
        view.add_item(_DeliveryModeSelect())
        view.add_item(_RenewalChannelPicker())
        view.add_item(_BackToRenewalMenuButton())
        await interaction.response.edit_message(
            content="Escolha por onde os avisos são enviados e o canal de renovações:",
            embed=None,
            view=view,
        )

    @discord.ui.button(label="⏱️ Frequência", style=discord.ButtonStyle.primary, row=1)
    async def interval_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        view = SafeView(timeout=180)
        view.add_item(_IntervalSelect())
        view.add_item(_BackToRenewalMenuButton())
        await interaction.response.edit_message(
            content="Com que frequência o bot verifica as assinaturas?", embed=None, view=view
        )

    @discord.ui.button(label="🕒 Carência", style=discord.ButtonStyle.primary, row=1)
    async def grace_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        view = SafeView(timeout=180)
        view.add_item(_GraceSelect())
        view.add_item(_BackToRenewalMenuButton())
        await interaction.response.edit_message(
            content="Quantos dias de carência depois do vencimento?", embed=None, view=view
        )

    @discord.ui.button(label="🧹 Remoção automática", style=discord.ButtonStyle.primary, row=1)
    async def removal_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        view = SafeView(timeout=180)
        view.add_item(_RemovalToggleSelect(self.settings))
        view.add_item(_BackToRenewalMenuButton())
        await interaction.response.edit_message(
            content="Selecione o que alternar (liga/desliga):", embed=None, view=view
        )

    @discord.ui.button(label="💬 Mensagens", style=discord.ButtonStyle.secondary, row=2)
    async def messages_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        view = SafeView(timeout=180)
        view.add_item(_MessageTypeSelect())
        view.add_item(_BackToRenewalMenuButton())
        await interaction.response.edit_message(
            content="Escolha qual mensagem editar:", embed=None, view=view
        )

    @discord.ui.button(label="🔘 Botões", style=discord.ButtonStyle.secondary, row=2)
    async def buttons_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await interaction.response.defer()
        await render_buttons_menu(interaction)

    @discord.ui.button(label="📊 Painel administrativo", style=discord.ButtonStyle.secondary, row=2)
    async def admin_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await interaction.response.defer()
        await render_admin_panel(interaction, page=0)

    @discord.ui.button(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        from views.monetization_panel_view import (
            MonetizationMenuView,
            monetization_menu_embed,
        )

        await interaction.response.edit_message(
            content=None, embed=monetization_menu_embed(), view=MonetizationMenuView()
        )


class _BackToRenewalMenuButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await render_renewal_menu(interaction)


# --- canais / entrega -------------------------------------------------------


class _DeliveryModeSelect(discord.ui.Select[Any]):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Onde enviar os avisos...",
            options=[
                discord.SelectOption(label="Somente DM", value="dm"),
                discord.SelectOption(label="Somente Canal", value="channel"),
                discord.SelectOption(label="Ambos", value="both"),
                discord.SelectOption(label="Nenhum", value="none"),
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        mode = self.values[0]
        dm = mode in ("dm", "both")
        channel = mode in ("channel", "both")
        settings = await bot.subscription_renewal_config_service.get_settings(interaction.guild_id)
        before = _DELIVERY_LABELS[(settings.notify_via_dm, settings.notify_via_channel)]
        await bot.subscription_renewal_config_service.update_settings(
            interaction.guild_id, notify_via_dm=dm, notify_via_channel=channel
        )
        await _log_change(interaction, "Notificações", before, _DELIVERY_LABELS[(dm, channel)])
        await render_renewal_menu(interaction)


class _RenewalChannelPicker(discord.ui.ChannelSelect):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Canal de Renovações",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        settings = await bot.subscription_renewal_config_service.get_settings(interaction.guild_id)
        before = f"<#{settings.renewal_channel_id}>" if settings.renewal_channel_id else "—"
        channel_id = self.values[0].id
        await bot.subscription_renewal_config_service.update_settings(
            interaction.guild_id, renewal_channel_id=channel_id
        )
        await _log_change(interaction, "Canal de Renovações", before, f"<#{channel_id}>")
        await render_renewal_menu(interaction)


class _IntervalSelect(discord.ui.Select[Any]):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Frequência da verificação...",
            options=[
                discord.SelectOption(label=f"A cada {hours}h", value=str(hours))
                for hours in CHECK_INTERVAL_CHOICES
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        settings = await bot.subscription_renewal_config_service.get_settings(interaction.guild_id)
        before = f"{settings.check_interval_hours}h"
        hours = int(self.values[0])
        await bot.subscription_renewal_config_service.update_settings(
            interaction.guild_id, check_interval_hours=hours
        )
        await _log_change(interaction, "Frequência", before, f"{hours}h")
        await render_renewal_menu(interaction)


class _GraceSelect(discord.ui.Select[Any]):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Período de carência...",
            options=[
                discord.SelectOption(
                    label="Sem carência (remove na hora)" if days == 0 else f"{days} dia(s)",
                    value=str(days),
                )
                for days in GRACE_PERIOD_CHOICES
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        settings = await bot.subscription_renewal_config_service.get_settings(interaction.guild_id)
        before = f"{settings.grace_period_days} dia(s)"
        days = int(self.values[0])
        await bot.subscription_renewal_config_service.update_settings(
            interaction.guild_id, grace_period_days=days
        )
        await _log_change(interaction, "Período de carência", before, f"{days} dia(s)")
        await render_renewal_menu(interaction)


_REMOVAL_FIELDS = {
    "remove_roles_on_expire": "Remover cargos ao expirar",
    "remove_benefits_on_expire": "Remover benefícios ao expirar",
    "end_subscription_on_expire": "Encerrar assinatura ao expirar",
    "send_dm_on_removal": "Enviar DM ao remover",
    "log_audit": "Registrar na auditoria",
    "continue_reminders_during_grace": "Continuar avisos na carência",
}


class _RemovalToggleSelect(discord.ui.Select[Any]):
    def __init__(self, settings: SubscriptionRenewalSettings) -> None:
        super().__init__(
            placeholder="Alternar configuração...",
            options=[
                discord.SelectOption(
                    label=label, value=attr, description=_onoff(getattr(settings, attr))
                )
                for attr, label in _REMOVAL_FIELDS.items()
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        attr = self.values[0]
        settings = await bot.subscription_renewal_config_service.get_settings(interaction.guild_id)
        before = bool(getattr(settings, attr))
        await bot.subscription_renewal_config_service.update_settings(
            interaction.guild_id, **{attr: not before}
        )
        await _log_change(interaction, _REMOVAL_FIELDS[attr], _onoff(before), _onoff(not before))
        await render_renewal_menu(interaction)


# --- avisos (dias antes) ----------------------------------------------------


async def render_days_menu(interaction: discord.Interaction) -> None:
    assert interaction.guild_id is not None
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    days = await bot.subscription_renewal_config_service.list_reminder_days(interaction.guild_id)
    embed = discord.Embed(
        title="⏰ Avisos antes do vencimento",
        description=(
            "Quantidade ilimitada. O **menor** valor configurado é tratado como o "
            "*último aviso* e usa a mensagem “Último aviso”."
        ),
        color=EMBED_COLOR_DEFAULT,
    )
    if days:
        for index, day in enumerate(days):
            embed.add_field(
                name=f"{index + 1}. {day.days_before} dia(s) antes",
                value=_onoff(day.enabled),
                inline=True,
            )
    else:
        embed.description = f"{embed.description}\n\nNenhum aviso configurado ainda."
    view = _ReminderDaysView(days)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embed=embed, view=view)
    else:
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class _ReminderDaysView(SafeView):
    def __init__(self, days: list) -> None:
        super().__init__(timeout=300)
        self.days = days
        if days:
            self.add_item(_ReminderDayActionSelect(days))
        self.add_item(_AddReminderDayButton())
        self.add_item(_BackToRenewalMenuButton())


class _ReminderDayActionSelect(discord.ui.Select[Any]):
    def __init__(self, days: list) -> None:
        options = [
            discord.SelectOption(
                label=f"{day.days_before} dia(s) antes",
                value=str(day.id),
                description=_onoff(day.enabled),
            )
            for day in days
        ][:25]
        super().__init__(placeholder="Selecione um aviso...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        day_id = uuid.UUID(self.values[0])
        view = SafeView(timeout=180)
        view.add_item(_ReminderDayToggleButton(day_id))
        view.add_item(_ReminderDayMoveButton(day_id, delta=-1))
        view.add_item(_ReminderDayMoveButton(day_id, delta=1))
        view.add_item(_ReminderDayRemoveButton(day_id))
        view.add_item(_BackToDaysButton())
        await interaction.response.edit_message(
            content="O que deseja fazer com este aviso?", embed=None, view=view
        )


class _BackToDaysButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await render_days_menu(interaction)


class _ReminderDayToggleButton(discord.ui.Button[Any]):
    def __init__(self, day_id: uuid.UUID) -> None:
        super().__init__(label="Ativar/Desativar", style=discord.ButtonStyle.primary)
        self.day_id = day_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        day = await bot.subscription_renewal_config_service.toggle_reminder_day(
            self.day_id, guild_id=interaction.guild_id
        )
        if day is not None:
            await _log_change(
                interaction,
                f"Aviso {day.days_before} dia(s)",
                _onoff(not day.enabled),
                _onoff(day.enabled),
            )
        await render_days_menu(interaction)


class _ReminderDayMoveButton(discord.ui.Button[Any]):
    def __init__(self, day_id: uuid.UUID, *, delta: int) -> None:
        super().__init__(
            label="🔼 Subir" if delta < 0 else "🔽 Descer", style=discord.ButtonStyle.secondary
        )
        self.day_id = day_id
        self.delta = delta

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        await bot.subscription_renewal_config_service.move_reminder_day(
            self.day_id, guild_id=interaction.guild_id, delta=self.delta
        )
        await render_days_menu(interaction)


class _ReminderDayRemoveButton(discord.ui.Button[Any]):
    def __init__(self, day_id: uuid.UUID) -> None:
        super().__init__(label="🗑️ Remover", style=discord.ButtonStyle.danger)
        self.day_id = day_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        await bot.subscription_renewal_config_service.remove_reminder_day(
            self.day_id, guild_id=interaction.guild_id
        )
        await _log_change(interaction, "Aviso removido", "—", str(self.day_id))
        await render_days_menu(interaction)


class _AddReminderDayButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(label="➕ Adicionar aviso", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(_AddReminderDayModal())


class _AddReminderDayModal(discord.ui.Modal, title="Novo aviso de renovação"):
    days_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Quantos dias antes do vencimento?", placeholder="Ex: 7", max_length=4
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        raw = str(self.days_input.value).strip()
        if not raw.isdigit():
            await interaction.response.send_message("Digite um número inteiro.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            day = await bot.subscription_renewal_config_service.add_reminder_day(
                interaction.guild_id, int(raw)
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await _log_change(interaction, "Aviso adicionado", "—", f"{day.days_before} dia(s) antes")
        await render_days_menu(interaction)


# --- mensagens --------------------------------------------------------------


class _MessageTypeSelect(discord.ui.Select[Any]):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Tipo de mensagem...",
            options=[
                discord.SelectOption(label=label, value=message_type.value)
                for message_type, label in _MESSAGE_TYPE_LABELS.items()
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        message_type = SubscriptionMessageType(self.values[0])
        content = await bot.subscription_renewal_config_service.get_message_content(
            interaction.guild_id, message_type
        )
        await interaction.response.send_modal(_MessageEditModal(message_type, content))


class _MessageEditModal(discord.ui.Modal):
    content_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Mensagem", style=discord.TextStyle.paragraph, required=False, max_length=2000
    )

    def __init__(self, message_type: SubscriptionMessageType, current: str) -> None:
        super().__init__(title=f"Mensagem — {_MESSAGE_TYPE_LABELS[message_type]}"[:45])
        self.message_type = message_type
        self.content_input.default = current
        self.content_input.placeholder = f"Placeholders: {_PLACEHOLDER_HELP}"[:100]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        content = str(self.content_input.value).strip()
        label = _MESSAGE_TYPE_LABELS[self.message_type]
        if content:
            await bot.subscription_renewal_config_service.set_message(
                interaction.guild_id, self.message_type, content
            )
            await _log_change(interaction, f"Mensagem: {label}", "(anterior)", content[:400])
        else:
            # vazio = volta pro texto padrão (que continua editável)
            await bot.subscription_renewal_config_service.reset_message(
                interaction.guild_id, self.message_type
            )
            await _log_change(
                interaction,
                f"Mensagem: {label}",
                "(personalizada)",
                DEFAULT_MESSAGES[self.message_type][:400],
            )
        await render_renewal_menu(interaction)


# --- botoes -----------------------------------------------------------------


async def render_buttons_menu(interaction: discord.Interaction) -> None:
    assert interaction.guild_id is not None
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    buttons = await bot.subscription_renewal_config_service.list_buttons(interaction.guild_id)
    embed = discord.Embed(
        title="🔘 Botões das mensagens de renovação",
        description=(
            "O botão **Renovar** reaproveita o fluxo de compra da Loja — nenhum "
            "gateway é chamado direto por aqui."
        ),
        color=EMBED_COLOR_DEFAULT,
    )
    for button in sorted(buttons, key=lambda b: b.position):
        embed.add_field(
            name=f"{button.emoji or ''} {button.label or _BUTTON_LABELS[button.key]}".strip(),
            value=_onoff(button.enabled),
            inline=True,
        )
    view = SafeView(timeout=300)
    view.add_item(_ButtonPickSelect(buttons))
    view.add_item(_BackToRenewalMenuButton())
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embed=embed, view=view)
    else:
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class _ButtonPickSelect(discord.ui.Select[Any]):
    def __init__(self, buttons: list) -> None:
        super().__init__(
            placeholder="Selecione um botão...",
            options=[
                discord.SelectOption(
                    label=button.label or _BUTTON_LABELS[button.key],
                    value=button.key.value,
                    description=_onoff(button.enabled),
                )
                for button in sorted(buttons, key=lambda b: b.position)
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        key = SubscriptionRenewalButtonKey(self.values[0])
        view = SafeView(timeout=180)
        view.add_item(_ButtonToggleButton(key))
        view.add_item(_ButtonEditButton(key))
        view.add_item(_BackToButtonsButton())
        await interaction.response.edit_message(
            content=f"Botão **{_BUTTON_LABELS[key]}** — o que deseja fazer?", embed=None, view=view
        )


class _BackToButtonsButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await render_buttons_menu(interaction)


class _ButtonToggleButton(discord.ui.Button[Any]):
    def __init__(self, key: SubscriptionRenewalButtonKey) -> None:
        super().__init__(label="Ativar/Desativar", style=discord.ButtonStyle.primary)
        self.key = key

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        button = await bot.subscription_renewal_config_service.toggle_button(
            interaction.guild_id, self.key
        )
        await _log_change(
            interaction,
            f"Botão: {_BUTTON_LABELS[self.key]}",
            _onoff(not button.enabled),
            _onoff(button.enabled),
        )
        await render_buttons_menu(interaction)


class _ButtonEditButton(discord.ui.Button[Any]):
    def __init__(self, key: SubscriptionRenewalButtonKey) -> None:
        super().__init__(label="✏️ Texto/Emoji", style=discord.ButtonStyle.secondary)
        self.key = key

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        buttons = await bot.subscription_renewal_config_service.list_buttons(interaction.guild_id)
        current = next((b for b in buttons if b.key == self.key), None)
        await interaction.response.send_modal(
            _ButtonEditModal(
                self.key,
                current.label if current else None,
                current.emoji if current else None,
            )
        )


class _ButtonEditModal(discord.ui.Modal):
    def __init__(
        self, key: SubscriptionRenewalButtonKey, label: str | None, emoji: str | None
    ) -> None:
        super().__init__(title=f"Botão — {_BUTTON_LABELS[key]}"[:45])
        self.key = key
        self.label_input = discord.ui.TextInput(
            label="Texto do botão", default=label or "", required=False, max_length=80
        )
        self.emoji_input = discord.ui.TextInput(
            label="Emoji", default=emoji or "", required=False, max_length=64
        )
        self.add_item(self.label_input)
        self.add_item(self.emoji_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        label = str(self.label_input.value).strip() or None
        emoji = str(self.emoji_input.value).strip() or None
        await bot.subscription_renewal_config_service.update_button(
            interaction.guild_id, self.key, label=label, emoji=emoji
        )
        await _log_change(
            interaction,
            f"Botão: {_BUTTON_LABELS[self.key]}",
            "(anterior)",
            f"{emoji or ''} {label or _BUTTON_LABELS[self.key]}".strip(),
        )
        await render_buttons_menu(interaction)


# --- painel administrativo --------------------------------------------------


_STATUS_LABELS = {
    SubscriptionStatus.PENDING: "⏳ Pendente",
    SubscriptionStatus.ACTIVE: "✅ Ativa",
    SubscriptionStatus.CANCELED: "🚫 Cancelada",
    SubscriptionStatus.EXPIRED: "⌛ Expirada",
}


async def render_admin_panel(interaction: discord.Interaction, *, page: int) -> None:
    """Lista assinaturas + estado dos lembretes (paginado, mesmo formato do
    /config history)."""
    from datetime import UTC, datetime, timedelta

    assert interaction.guild_id is not None
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    settings = await bot.subscription_renewal_config_service.get_settings(interaction.guild_id)
    subscriptions = await bot.subscription_service.list_guild_subscriptions(interaction.guild_id)
    subscriptions.sort(
        key=lambda s: s.current_period_end.timestamp()
        if s.current_period_end is not None
        else float("inf")
    )

    total_pages = max(1, (len(subscriptions) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    window = subscriptions[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    now = datetime.now(UTC)
    embed = discord.Embed(title="📊 Assinaturas — painel de renovação", color=EMBED_COLOR_DEFAULT)
    if not window:
        embed.description = "Nenhuma assinatura registrada neste servidor."
    for subscription in window:
        plan = await bot.plan_service.get_plan(subscription.plan_id)
        reminders = await bot.subscription_reminder_service.list_reminders(subscription.id)
        period_end = subscription.current_period_end
        if period_end is not None and period_end.tzinfo is None:
            period_end = period_end.replace(tzinfo=UTC)
        days_left = (period_end - now).days if period_end is not None else None
        in_grace = (
            period_end is not None
            and period_end <= now
            and now < period_end + timedelta(days=settings.grace_period_days)
        )
        last = reminders[0] if reminders else None
        embed.add_field(
            name=f"{plan.name if plan else 'Plano removido'} — <@{subscription.user_id}>",
            value=(
                f"Início: {subscription.started_at.strftime('%d/%m/%Y') if subscription.started_at else '—'}\n"
                f"Expiração: {period_end.strftime('%d/%m/%Y') if period_end else '—'}\n"
                f"Dias restantes: {days_left if days_left is not None else '—'}\n"
                f"Carência: {'🕒 em carência' if in_grace else '—'}\n"
                f"Status: {_STATUS_LABELS.get(subscription.status, subscription.status.value)}\n"
                f"Último lembrete: {last.reminder_type + ' (' + last.sent_at.strftime('%d/%m/%Y') + ')' if last else '—'}\n"
                f"Lembretes enviados: {len(reminders)}"
            ),
            inline=False,
        )
    embed.set_footer(text=f"Página {page + 1}/{total_pages} — {len(subscriptions)} assinatura(s)")

    view = _AdminPanelView(page, total_pages)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embed=embed, view=view)
    else:
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class _AdminPanelView(SafeView):
    def __init__(self, page: int, total_pages: int) -> None:
        super().__init__(timeout=300)
        self.page = page
        self.total_pages = total_pages
        self._previous.disabled = page <= 0
        self._next.disabled = page >= total_pages - 1

    @discord.ui.button(label="◀ Anterior", style=discord.ButtonStyle.secondary)
    async def _previous(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await interaction.response.defer()
        await render_admin_panel(interaction, page=self.page - 1)

    @discord.ui.button(label="Próxima ▶", style=discord.ButtonStyle.secondary)
    async def _next(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await interaction.response.defer()
        await render_admin_panel(interaction, page=self.page + 1)

    @discord.ui.button(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=1)
    async def _back(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await interaction.response.defer()
        await render_renewal_menu(interaction)
