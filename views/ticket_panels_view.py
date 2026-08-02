from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import discord
from views.base_view import SafeView

from database.models.ticket_panel import TicketPanel
from database.models.ticket_panel_form_field import (
    FORM_FIELD_STYLES,
    MAX_FORM_FIELDS,
    TicketPanelFormField,
)
from services.ticket_panel_service import BUTTON_STYLE_LABELS, TicketPanelError
from utils.constants import EMBED_COLOR_DEFAULT, EMBED_COLOR_WARNING

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_CATEGORY_CHANNEL = [discord.ChannelType.category]
_TEXT = [discord.ChannelType.text, discord.ChannelType.news]

# toggles de comportamento do painel: attr -> rotulo mostrado no /config
_BEHAVIOUR_TOGGLES: dict[str, str] = {
    "allow_multiple_tickets": "Permitir múltiplos tickets",
    "auto_close_enabled": "Auto-close ativado",
    "transcript_enabled": "Transcrição ativada",
    "evaluation_enabled": "Avaliação ativada",
    "dm_on_close_enabled": "DM ao fechar",
}


def _bool_label(value: bool) -> str:
    return "✅ Ativado" if value else "❌ Desativado"


async def _log_panel_change(
    interaction: discord.Interaction,
    panel: TicketPanel,
    field_label: str,
    before: object,
    after: object,
) -> None:
    """Toda edição de painel entra no mesmo histórico de auditoria do /config
    (categoria "Tickets") — sem plumbing novo de log."""
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    if interaction.guild_id is None:
        return
    await bot.audit_log_service.record_config_change(
        guild_id=interaction.guild_id,
        actor_id=interaction.user.id,
        actor_name=str(interaction.user),
        config_category="Tickets",
        config_name=f"Painel {panel.name} — {field_label}",
        old_value=str(before) if before not in (None, "") else "—",
        new_value=str(after) if after not in (None, "") else "—",
    )


# =========================== menu principal ================================


def tickets_menu_embed(*, enabled: bool, panel_count: int) -> discord.Embed:
    embed = discord.Embed(
        title="🎫 Tickets",
        description=(
            "Crie quantos painéis de abertura de ticket quiser (Suporte, Compras, "
            "Denúncias, Parcerias...). Cada painel tem canal, categoria, cargos, "
            "embed, botão, comportamento, formulário e aprovação próprios."
        ),
        color=EMBED_COLOR_DEFAULT,
    )
    embed.add_field(name="Sistema de Tickets", value=_bool_label(enabled))
    embed.add_field(name="Painéis cadastrados", value=str(panel_count))
    embed.set_footer(
        text=(
            "Com o sistema desativado ninguém abre ticket novo — os tickets já "
            "abertos continuam funcionando normalmente."
        )
    )
    return embed


async def render_tickets_menu(interaction: discord.Interaction, on_back: Any = None) -> None:
    assert interaction.guild_id is not None
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    settings = await bot.config_service.get_ticket_settings(interaction.guild_id)
    panels = await bot.ticket_panel_service.list_panels(interaction.guild_id)
    embed = tickets_menu_embed(enabled=settings.enabled, panel_count=len(panels))
    view = TicketsMenuView(on_back=on_back, enabled=settings.enabled)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embed=embed, view=view)
    else:
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class TicketsMenuView(SafeView):
    """Tela inicial da categoria Tickets do /config: kill switch do sistema,
    entrada pros painéis e as configurações globais/legadas (canais da guild)."""

    def __init__(self, on_back: Any = None, *, enabled: bool = True) -> None:
        super().__init__(timeout=300)
        self.on_back = on_back
        self.toggle_system.label = (
            "🚫 Desativar sistema" if enabled else "✅ Ativar sistema"
        )
        self.toggle_system.style = (
            discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success
        )
        if on_back is not None:
            self.add_item(_BackToMainMenuButton(on_back))

    @discord.ui.button(label="📋 Painéis de Tickets", style=discord.ButtonStyle.primary, row=0)
    async def panels_button(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await _render_panels_list(interaction, self.on_back)

    @discord.ui.button(label="🚫 Desativar sistema", style=discord.ButtonStyle.danger, row=0)
    async def toggle_system(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        settings = await bot.config_service.get_ticket_settings(interaction.guild_id)
        before = settings.enabled
        await bot.config_service.update_ticket_settings(interaction.guild_id, enabled=not before)
        await bot.audit_log_service.record_config_change(
            guild_id=interaction.guild_id,
            actor_id=interaction.user.id,
            actor_name=str(interaction.user),
            config_category="Tickets",
            config_name="Sistema de Tickets",
            old_value=_bool_label(before),
            new_value=_bool_label(not before),
        )
        await render_tickets_menu(interaction, self.on_back)

    @discord.ui.button(label="⚙️ Configurações Gerais", style=discord.ButtonStyle.secondary, row=1)
    async def general_button(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        """Canais globais da guild (categoria padrão, logs, transcrição, alerta,
        blacklist) + comportamento global. Continuam existindo porque não são
        específicos de painel e são usados pelo fluxo legado /painel-setup e por
        outras partes do bot (transcrição, blacklist, avaliações)."""
        # import tardio: master_config_view importa este módulo
        from views.master_config_view import _tickets_category
        from views.settings_panel import DomainSettingsView, build_domain_embed

        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        fields, get_settings, update_settings = _tickets_category(bot)
        on_back = self.on_back

        async def _back(inner: discord.Interaction) -> None:
            await render_tickets_menu(inner, on_back)

        view = DomainSettingsView(
            title="🎫 Tickets — Configurações Gerais",
            fields=fields,
            get_settings=get_settings,
            update_settings=update_settings,
            on_back=_back,
        )
        settings = await get_settings(interaction.guild_id)
        await interaction.response.edit_message(
            content=None,
            embed=build_domain_embed(view.title, fields, settings),
            view=view,
        )


class _BackToMainMenuButton(discord.ui.Button[Any]):
    def __init__(self, on_back: Any) -> None:
        super().__init__(label="◀ Menu principal", style=discord.ButtonStyle.secondary, row=4)
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.on_back(interaction)


# ============================ lista de painéis =============================


def panels_list_embed(panels: list[TicketPanel]) -> discord.Embed:
    embed = discord.Embed(title="📋 Painéis de Tickets", color=EMBED_COLOR_DEFAULT)
    if not panels:
        embed.description = (
            "Nenhum painel criado ainda. Use **➕ Criar Painel** pra criar o primeiro."
        )
        return embed
    for panel in panels:
        status = "✅ Ativo" if panel.enabled else "🚫 Inativo"
        published = f"<#{panel.channel_id}>" if panel.channel_id else "não publicado"
        embed.add_field(name=panel.name, value=f"{status} · {published}", inline=True)
    return embed


async def _render_panels_list(interaction: discord.Interaction, on_back: Any = None) -> None:
    assert interaction.guild_id is not None
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    panels = await bot.ticket_panel_service.list_panels(interaction.guild_id)
    view = TicketPanelsListView(panels, on_back)
    if interaction.response.is_done():
        await interaction.edit_original_response(
            content=None, embed=panels_list_embed(panels), view=view
        )
    else:
        await interaction.response.edit_message(
            content=None, embed=panels_list_embed(panels), view=view
        )


class TicketPanelsListView(SafeView):
    def __init__(self, panels: list[TicketPanel], on_back: Any = None) -> None:
        super().__init__(timeout=300)
        self.on_back = on_back
        if panels:
            self.add_item(_PanelSelect(panels, on_back))
        self.add_item(_CreatePanelButton(on_back))
        self.add_item(_BackToTicketsMenuButton(on_back))


class _PanelSelect(discord.ui.Select[Any]):
    def __init__(self, panels: list[TicketPanel], on_back: Any) -> None:
        options = [
            discord.SelectOption(
                label=panel.name[:100],
                value=str(panel.id),
                description=("Ativo" if panel.enabled else "Inativo"),
            )
            for panel in panels
        ][:25]
        super().__init__(
            placeholder="Selecione um painel pra editar...",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        panel = await bot.ticket_panel_service.get_panel(uuid.UUID(self.values[0]))
        if panel is None or panel.guild_id != interaction.guild_id:
            await interaction.response.send_message("Painel não encontrado.", ephemeral=True)
            return
        await _render_panel_edit(interaction, panel, self.on_back)


class _CreatePanelButton(discord.ui.Button[Any]):
    def __init__(self, on_back: Any) -> None:
        super().__init__(label="➕ Criar Painel", style=discord.ButtonStyle.success)
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(_CreatePanelModal(self.on_back))


class _CreatePanelModal(discord.ui.Modal, title="Criar Painel de Tickets"):
    name_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Nome do painel",
        placeholder="Ex: Suporte, Compras, Denúncias, Parcerias...",
        max_length=100,
    )

    def __init__(self, on_back: Any) -> None:
        super().__init__()
        self.on_back = on_back

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        try:
            panel = await bot.ticket_panel_service.create_panel(
                interaction.guild_id, str(self.name_input.value)
            )
        except TicketPanelError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await bot.audit_log_service.record_config_change(
            guild_id=interaction.guild_id,
            actor_id=interaction.user.id,
            actor_name=str(interaction.user),
            config_category="Tickets",
            config_name="Painel criado",
            old_value="—",
            new_value=panel.name,
        )
        await _render_panel_edit(interaction, panel, self.on_back)


class _BackToTicketsMenuButton(discord.ui.Button[Any]):
    def __init__(self, on_back: Any) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary)
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await render_tickets_menu(interaction, self.on_back)


# ============================ editor do painel =============================


async def panel_edit_embed(bot: "LimerenceBot", panel: TicketPanel) -> discord.Embed:
    color = (
        discord.Color(panel.embed_color) if panel.embed_color is not None else EMBED_COLOR_WARNING
    )
    embed = discord.Embed(title=f"🎫 {panel.name}", color=color)
    embed.description = panel.embed_description or "*(sem descrição na embed)*"
    embed.add_field(name="Status", value="✅ Ativo" if panel.enabled else "🚫 Inativo")
    embed.add_field(
        name="Publicado em", value=f"<#{panel.channel_id}>" if panel.channel_id else "—"
    )
    embed.add_field(
        name="Categoria dos tickets",
        value=f"<#{panel.ticket_category_id}>" if panel.ticket_category_id else "— (usa a global)",
    )
    embed.add_field(
        name="Cargos responsáveis",
        value=(
            ", ".join(f"<@&{r}>" for r in panel.responsible_role_ids)
            if panel.responsible_role_ids
            else "— (usa a staff global)"
        ),
        inline=False,
    )
    embed.add_field(
        name="Quem pode assumir",
        value=(
            ", ".join(f"<@&{r}>" for r in panel.claim_role_ids)
            if panel.claim_role_ids
            else "— (permissão global de Assumir)"
        ),
        inline=False,
    )
    embed.add_field(
        name="Botão",
        value=(
            f"{panel.button_emoji or ''} {panel.button_label or f'Abrir {panel.name}'} "
            f"({BUTTON_STYLE_LABELS.get(panel.button_style, panel.button_style)})"
        ).strip(),
    )
    limit = panel.max_tickets_per_user
    embed.add_field(name="Limite por usuário", value=str(limit) if limit else "— (usa o global)")
    embed.add_field(name="Delay de exclusão", value=f"{panel.delete_delay_seconds}s")
    embed.add_field(
        name="Comportamento",
        value="\n".join(
            f"{_bool_label(getattr(panel, attr))} · {label}"
            for attr, label in _BEHAVIOUR_TOGGLES.items()
        ),
        inline=False,
    )
    fields = await bot.ticket_panel_service.list_form_fields(panel.id)
    embed.add_field(
        name="Formulário",
        value=(
            f"{_bool_label(panel.form_enabled)} · {len(fields)}/{MAX_FORM_FIELDS} pergunta(s)"
        ),
    )
    embed.add_field(
        name="Aprovação",
        value=(
            f"{_bool_label(panel.approval_enabled)}"
            + (
                f" · cargo <@&{panel.approval_granted_role_id}>"
                if panel.approval_granted_role_id
                else ""
            )
        ),
    )
    return embed


async def _render_panel_edit(
    interaction: discord.Interaction, panel: TicketPanel, on_back: Any = None
) -> None:
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    embed = await panel_edit_embed(bot, panel)
    view = TicketPanelEditView(panel, on_back)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embed=embed, view=view)
    else:
        await interaction.response.edit_message(content=None, embed=embed, view=view)
    # mantém a mensagem já publicada sincronizada com a config nova
    if panel.channel_id is not None and panel.message_id is not None:
        await bot.ticket_panel_service.refresh_panel(panel.id)


class TicketPanelEditView(SafeView):
    """Editor de UM painel — mesma forma do PlanEditView da Monetização: um
    botão por seção, cada um abrindo um modal/picker e re-renderizando."""

    def __init__(self, panel: TicketPanel, on_back: Any = None) -> None:
        super().__init__(timeout=300)
        self.panel = panel
        self.on_back = on_back
        self.toggle_enabled.label = "🚫 Desativar" if panel.enabled else "✅ Ativar"

    # --- linha 0: identidade e aparência ---
    @discord.ui.button(label="✏️ Nome", style=discord.ButtonStyle.primary, row=0)
    async def name_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await interaction.response.send_modal(_PanelNameModal(self.panel, self.on_back))

    @discord.ui.button(label="🎨 Embed", style=discord.ButtonStyle.primary, row=0)
    async def embed_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        view = SafeView(timeout=180)
        view.add_item(_EmbedTextButton(self.panel, self.on_back))
        view.add_item(_EmbedImagesButton(self.panel, self.on_back))
        view.add_item(_BackToPanelEditButton(self.panel, self.on_back))
        await interaction.response.edit_message(
            content="**Embed do painel** — o que deseja editar?", embed=None, view=view
        )

    @discord.ui.button(label="🔘 Botão", style=discord.ButtonStyle.primary, row=0)
    async def button_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        view = SafeView(timeout=180)
        view.add_item(_ButtonStyleSelect(self.panel, self.on_back))
        view.add_item(_ButtonTextButton(self.panel, self.on_back))
        view.add_item(_BackToPanelEditButton(self.panel, self.on_back))
        await interaction.response.edit_message(
            content="**Botão de abrir ticket** — texto/emoji e cor.", embed=None, view=view
        )

    @discord.ui.button(label="⚙️ Comportamento", style=discord.ButtonStyle.primary, row=0)
    async def behaviour_button(
        self, interaction: discord.Interaction, _b: discord.ui.Button
    ) -> None:
        view = SafeView(timeout=180)
        view.add_item(_BehaviourToggleSelect(self.panel, self.on_back))
        view.add_item(_LimitsButton(self.panel, self.on_back))
        view.add_item(_BackToPanelEditButton(self.panel, self.on_back))
        await interaction.response.edit_message(
            content="**Comportamento do painel** — toggles e limites.", embed=None, view=view
        )

    # --- linha 1: canais/cargos/formulário ---
    @discord.ui.button(label="📁 Categoria", style=discord.ButtonStyle.secondary, row=1)
    async def category_button(
        self, interaction: discord.Interaction, _b: discord.ui.Button
    ) -> None:
        view = SafeView(timeout=180)
        view.add_item(_TicketCategoryPicker(self.panel, self.on_back))
        view.add_item(_BackToPanelEditButton(self.panel, self.on_back))
        await interaction.response.edit_message(
            content="Categoria onde os canais de ticket deste painel serão criados:",
            embed=None,
            view=view,
        )

    @discord.ui.button(label="🎭 Responsáveis", style=discord.ButtonStyle.secondary, row=1)
    async def roles_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        view = SafeView(timeout=180)
        view.add_item(_ResponsibleRolesPicker(self.panel, self.on_back))
        view.add_item(_BackToPanelEditButton(self.panel, self.on_back))
        await interaction.response.edit_message(
            content=(
                "Cargos com acesso aos tickets deste painel (vazio = usa a staff global "
                "configurada em Cargos):"
            ),
            embed=None,
            view=view,
        )

    @discord.ui.button(label="🛡️ Quem assume", style=discord.ButtonStyle.secondary, row=1)
    async def claim_roles_button(
        self, interaction: discord.Interaction, _b: discord.ui.Button
    ) -> None:
        view = SafeView(timeout=180)
        view.add_item(_ClaimRolesPicker(self.panel, self.on_back))
        view.add_item(_BackToPanelEditButton(self.panel, self.on_back))
        await interaction.response.edit_message(
            content=(
                "Restringir ainda mais quem pode **Assumir/Analisar** os tickets deste painel "
                "(vazio = vale só a permissão global de Assumir):"
            ),
            embed=None,
            view=view,
        )

    @discord.ui.button(label="📝 Formulário", style=discord.ButtonStyle.secondary, row=1)
    async def form_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await _render_form_editor(interaction, self.panel, self.on_back)

    # --- linha 2: aprovação e publicação ---
    @discord.ui.button(label="🧾 Aprovação", style=discord.ButtonStyle.secondary, row=2)
    async def approval_button(
        self, interaction: discord.Interaction, _b: discord.ui.Button
    ) -> None:
        view = SafeView(timeout=180)
        view.add_item(_ApprovalToggleButton(self.panel, self.on_back))
        view.add_item(_ApprovalRolePicker(self.panel, self.on_back))
        view.add_item(_BackToPanelEditButton(self.panel, self.on_back))
        await interaction.response.edit_message(
            content=(
                f"**Aprovação** — {_bool_label(self.panel.approval_enabled)}\n"
                "Com aprovação ligada, cada ticket deste painel ganha botões "
                "Aprovar/Reprovar pra staff. Aprovar entrega o cargo abaixo, avisa o autor "
                "por DM e registra na auditoria."
            ),
            embed=None,
            view=view,
        )

    @discord.ui.button(label="📢 Publicar", style=discord.ButtonStyle.success, row=2)
    async def publish_button(
        self, interaction: discord.Interaction, _b: discord.ui.Button
    ) -> None:
        view = SafeView(timeout=180)
        view.add_item(_PublishChannelPicker(self.panel, self.on_back))
        view.add_item(_BackToPanelEditButton(self.panel, self.on_back))
        await interaction.response.edit_message(
            content="Em qual canal publicar este painel?", embed=None, view=view
        )

    @discord.ui.button(label="🔄 Atualizar", style=discord.ButtonStyle.secondary, row=2)
    async def refresh_button(
        self, interaction: discord.Interaction, _b: discord.ui.Button
    ) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        if self.panel.channel_id is None:
            await interaction.response.send_message(
                "Este painel ainda não foi publicado em nenhum canal.", ephemeral=True
            )
            return
        panel = await bot.ticket_panel_service.refresh_panel(self.panel.id)
        await _render_panel_edit(interaction, panel or self.panel, self.on_back)

    @discord.ui.button(label="🗑️ Despublicar", style=discord.ButtonStyle.secondary, row=2)
    async def unpublish_button(
        self, interaction: discord.Interaction, _b: discord.ui.Button
    ) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        if self.panel.channel_id is None:
            await interaction.response.send_message(
                "Este painel não está publicado.", ephemeral=True
            )
            return
        panel = await bot.ticket_panel_service.unpublish_panel(self.panel.id)
        await _log_panel_change(interaction, panel, "Publicação", "publicado", "despublicado")
        await _render_panel_edit(interaction, panel, self.on_back)

    # --- linha 3: estado e exclusão ---
    @discord.ui.button(label="🚫 Desativar", style=discord.ButtonStyle.secondary, row=3)
    async def toggle_enabled(
        self, interaction: discord.Interaction, _b: discord.ui.Button
    ) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        before = self.panel.enabled
        panel = await bot.ticket_panel_service.update_panel(self.panel.id, enabled=not before)
        await _log_panel_change(
            interaction, panel, "Status", _bool_label(before), _bool_label(not before)
        )
        await _render_panel_edit(interaction, panel, self.on_back)

    @discord.ui.button(label="❌ Excluir", style=discord.ButtonStyle.danger, row=3)
    async def delete_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        view = SafeView(timeout=60)
        view.add_item(_ConfirmDeletePanelButton(self.panel, self.on_back))
        view.add_item(_BackToPanelEditButton(self.panel, self.on_back))
        await interaction.response.edit_message(
            content=(
                f"Excluir o painel **{self.panel.name}**? A mensagem publicada é apagada e os "
                "tickets já abertos por ele continuam existindo (ficam sem painel vinculado)."
            ),
            embed=None,
            view=view,
        )

    @discord.ui.button(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await _render_panels_list(interaction, self.on_back)


class _BackToPanelEditButton(discord.ui.Button[Any]):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=4)
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        panel = await bot.ticket_panel_service.get_panel(self.panel.id) or self.panel
        await _render_panel_edit(interaction, panel, self.on_back)


class _ConfirmDeletePanelButton(discord.ui.Button[Any]):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__(label="Confirmar exclusão", style=discord.ButtonStyle.danger)
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        name = self.panel.name
        await bot.ticket_panel_service.delete_panel(self.panel.id)
        await bot.audit_log_service.record_config_change(
            guild_id=interaction.guild_id,
            actor_id=interaction.user.id,
            actor_name=str(interaction.user),
            config_category="Tickets",
            config_name="Painel excluído",
            old_value=name,
            new_value="—",
        )
        await _render_panels_list(interaction, self.on_back)


# ------------------------------- modais ------------------------------------


class _PanelNameModal(discord.ui.Modal, title="Nome do painel"):
    name_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Nome", max_length=100
    )

    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__()
        self.panel = panel
        self.on_back = on_back
        self.name_input.default = panel.name

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        new_name = str(self.name_input.value).strip()
        if not new_name:
            await interaction.response.send_message("O nome não pode ficar vazio.", ephemeral=True)
            return
        before = self.panel.name
        panel = await bot.ticket_panel_service.update_panel(self.panel.id, name=new_name)
        await _log_panel_change(interaction, panel, "Nome", before, new_name)
        await _render_panel_edit(interaction, panel, self.on_back)


class _EmbedTextButton(discord.ui.Button[Any]):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__(label="📝 Texto e cor", style=discord.ButtonStyle.primary)
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(_EmbedTextModal(self.panel, self.on_back))


class _EmbedTextModal(discord.ui.Modal, title="Embed — texto e cor"):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__()
        self.panel = panel
        self.on_back = on_back
        self.title_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Título", default=panel.embed_title or "", required=False, max_length=256
        )
        self.description_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Descrição",
            style=discord.TextStyle.paragraph,
            default=panel.embed_description or "",
            required=False,
            max_length=2000,
        )
        self.color_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Cor em hexadecimal",
            placeholder="Ex: #5865F2 (vazio = cor padrão)",
            default=f"#{panel.embed_color:06X}" if panel.embed_color is not None else "",
            required=False,
            max_length=7,
        )
        self.footer_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Rodapé", default=panel.embed_footer or "", required=False, max_length=200
        )
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.color_input)
        self.add_item(self.footer_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        raw_color = str(self.color_input.value).strip().lstrip("#")
        color: int | None = None
        if raw_color:
            try:
                color = int(raw_color, 16)
            except ValueError:
                await interaction.response.send_message(
                    "Cor inválida — use um hexadecimal (ex: #5865F2).", ephemeral=True
                )
                return
        panel = await bot.ticket_panel_service.update_panel(
            self.panel.id,
            embed_title=str(self.title_input.value).strip() or None,
            embed_description=str(self.description_input.value).strip() or None,
            embed_color=color,
            embed_footer=str(self.footer_input.value).strip() or None,
        )
        await _log_panel_change(
            interaction, panel, "Embed (texto/cor)", self.panel.embed_title, panel.embed_title
        )
        await _render_panel_edit(interaction, panel, self.on_back)


class _EmbedImagesButton(discord.ui.Button[Any]):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__(label="🖼️ Imagem e thumbnail", style=discord.ButtonStyle.primary)
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(_EmbedImagesModal(self.panel, self.on_back))


def _valid_url(raw: str) -> bool:
    return raw.startswith("http://") or raw.startswith("https://")


class _EmbedImagesModal(discord.ui.Modal, title="Embed — imagens"):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__()
        self.panel = panel
        self.on_back = on_back
        self.image_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="URL da imagem (banner)",
            placeholder="https://... (vazio = sem imagem)",
            default=panel.embed_image_url or "",
            required=False,
            max_length=500,
        )
        self.thumb_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="URL da thumbnail",
            placeholder="https://... (vazio = sem thumbnail)",
            default=panel.embed_thumbnail_url or "",
            required=False,
            max_length=500,
        )
        self.add_item(self.image_input)
        self.add_item(self.thumb_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        image = str(self.image_input.value).strip()
        thumb = str(self.thumb_input.value).strip()
        for raw in (image, thumb):
            if raw and not _valid_url(raw):
                await interaction.response.send_message(
                    "URL inválida — precisa começar com http:// ou https://.", ephemeral=True
                )
                return
        panel = await bot.ticket_panel_service.update_panel(
            self.panel.id,
            embed_image_url=image or None,
            embed_thumbnail_url=thumb or None,
        )
        await _log_panel_change(
            interaction, panel, "Embed (imagens)", self.panel.embed_image_url, image or "—"
        )
        await _render_panel_edit(interaction, panel, self.on_back)


class _ButtonTextButton(discord.ui.Button[Any]):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__(label="✏️ Texto e emoji", style=discord.ButtonStyle.primary)
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(_ButtonTextModal(self.panel, self.on_back))


class _ButtonTextModal(discord.ui.Modal, title="Botão — texto e emoji"):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__()
        self.panel = panel
        self.on_back = on_back
        self.label_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Texto do botão",
            default=panel.button_label or "",
            required=False,
            max_length=80,
        )
        self.emoji_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Emoji do botão",
            placeholder="Ex: 🎫 (vazio = sem emoji)",
            default=panel.button_emoji or "",
            required=False,
            max_length=64,
        )
        self.add_item(self.label_input)
        self.add_item(self.emoji_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        before = self.panel.button_label
        panel = await bot.ticket_panel_service.update_panel(
            self.panel.id,
            button_label=str(self.label_input.value).strip() or None,
            button_emoji=str(self.emoji_input.value).strip() or None,
        )
        await _log_panel_change(interaction, panel, "Botão", before, panel.button_label)
        await _render_panel_edit(interaction, panel, self.on_back)


class _ButtonStyleSelect(discord.ui.Select[Any]):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__(
            placeholder="Cor do botão...",
            options=[
                discord.SelectOption(
                    label=label, value=value, default=(panel.button_style == value)
                )
                for value, label in BUTTON_STYLE_LABELS.items()
            ],
            min_values=1,
            max_values=1,
        )
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        before = self.panel.button_style
        panel = await bot.ticket_panel_service.update_panel(
            self.panel.id, button_style=self.values[0]
        )
        await _log_panel_change(interaction, panel, "Cor do botão", before, self.values[0])
        await _render_panel_edit(interaction, panel, self.on_back)


class _BehaviourToggleSelect(discord.ui.Select[Any]):
    """Igual ao padrão BOOL do settings_panel: escolher já inverte o valor."""

    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__(
            placeholder="Ligar/desligar uma opção...",
            options=[
                discord.SelectOption(
                    label=label,
                    value=attr,
                    description=_bool_label(getattr(panel, attr)),
                )
                for attr, label in _BEHAVIOUR_TOGGLES.items()
            ],
            min_values=1,
            max_values=1,
        )
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        attr = self.values[0]
        before = getattr(self.panel, attr)
        panel = await bot.ticket_panel_service.update_panel(self.panel.id, **{attr: not before})
        await _log_panel_change(
            interaction,
            panel,
            _BEHAVIOUR_TOGGLES[attr],
            _bool_label(before),
            _bool_label(not before),
        )
        await _render_panel_edit(interaction, panel, self.on_back)


class _LimitsButton(discord.ui.Button[Any]):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__(label="🔢 Limites", style=discord.ButtonStyle.primary)
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(_LimitsModal(self.panel, self.on_back))


class _LimitsModal(discord.ui.Modal, title="Limites do painel"):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__()
        self.panel = panel
        self.on_back = on_back
        self.max_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Máx. de tickets por usuário",
            placeholder="Vazio = usa o limite global do servidor",
            default=str(panel.max_tickets_per_user) if panel.max_tickets_per_user else "",
            required=False,
            max_length=4,
        )
        self.delay_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Delay de exclusão (segundos)",
            default=str(panel.delete_delay_seconds),
            max_length=5,
        )
        self.add_item(self.max_input)
        self.add_item(self.delay_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        raw_max = str(self.max_input.value).strip()
        raw_delay = str(self.delay_input.value).strip()
        if raw_max and not raw_max.isdigit():
            await interaction.response.send_message(
                "Máximo de tickets: digite um número inteiro ou deixe vazio.", ephemeral=True
            )
            return
        if not raw_delay.isdigit():
            await interaction.response.send_message(
                "Delay de exclusão: digite um número inteiro de segundos.", ephemeral=True
            )
            return
        before = self.panel.max_tickets_per_user
        panel = await bot.ticket_panel_service.update_panel(
            self.panel.id,
            max_tickets_per_user=int(raw_max) if raw_max else None,
            delete_delay_seconds=int(raw_delay),
        )
        await _log_panel_change(
            interaction, panel, "Limite por usuário", before, panel.max_tickets_per_user
        )
        await _render_panel_edit(interaction, panel, self.on_back)


# ------------------------------- pickers -----------------------------------


class _TicketCategoryPicker(discord.ui.ChannelSelect):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__(
            placeholder="Categoria dos tickets deste painel",
            channel_types=_CATEGORY_CHANNEL,
            min_values=1,
            max_values=1,
        )
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        before = self.panel.ticket_category_id
        panel = await bot.ticket_panel_service.update_panel(
            self.panel.id, ticket_category_id=self.values[0].id
        )
        await _log_panel_change(interaction, panel, "Categoria", before, self.values[0].id)
        await _render_panel_edit(interaction, panel, self.on_back)


class _ResponsibleRolesPicker(discord.ui.RoleSelect):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__(
            placeholder="Cargos responsáveis (vazio = staff global)",
            min_values=0,
            max_values=25,
        )
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        before = list(self.panel.responsible_role_ids or [])
        role_ids = [role.id for role in self.values]
        panel = await bot.ticket_panel_service.update_panel(
            self.panel.id, responsible_role_ids=role_ids
        )
        if sorted(before) != sorted(role_ids):
            await _log_panel_change(interaction, panel, "Cargos responsáveis", before, role_ids)
        await _render_panel_edit(interaction, panel, self.on_back)


class _ClaimRolesPicker(discord.ui.RoleSelect):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__(
            placeholder="Cargos que podem assumir (vazio = permissão global)",
            min_values=0,
            max_values=25,
        )
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        before = list(self.panel.claim_role_ids or [])
        role_ids = [role.id for role in self.values]
        panel = await bot.ticket_panel_service.update_panel(
            self.panel.id, claim_role_ids=role_ids
        )
        if sorted(before) != sorted(role_ids):
            await _log_panel_change(interaction, panel, "Quem pode assumir", before, role_ids)
        await _render_panel_edit(interaction, panel, self.on_back)


class _ApprovalToggleButton(discord.ui.Button[Any]):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__(
            label="🚫 Desativar aprovação" if panel.approval_enabled else "✅ Ativar aprovação",
            style=(
                discord.ButtonStyle.danger
                if panel.approval_enabled
                else discord.ButtonStyle.success
            ),
        )
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        before = self.panel.approval_enabled
        panel = await bot.ticket_panel_service.update_panel(
            self.panel.id, approval_enabled=not before
        )
        await _log_panel_change(
            interaction, panel, "Aprovação", _bool_label(before), _bool_label(not before)
        )
        await _render_panel_edit(interaction, panel, self.on_back)


class _ApprovalRolePicker(discord.ui.RoleSelect):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__(
            placeholder="Cargo entregue quando aprovado", min_values=1, max_values=1
        )
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        before = self.panel.approval_granted_role_id
        panel = await bot.ticket_panel_service.update_panel(
            self.panel.id, approval_granted_role_id=self.values[0].id
        )
        await _log_panel_change(
            interaction, panel, "Cargo da aprovação", before, self.values[0].id
        )
        await _render_panel_edit(interaction, panel, self.on_back)


class _PublishChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__(
            placeholder="Canal onde o painel será publicado",
            channel_types=_TEXT,
            min_values=1,
            max_values=1,
        )
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        channel = interaction.guild.get_channel(self.values[0].id) if interaction.guild else None
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Selecione um canal de texto válido.", ephemeral=True
            )
            return
        await interaction.response.defer()
        try:
            panel = await bot.ticket_panel_service.publish_panel(self.panel.id, channel)
        except TicketPanelError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await _log_panel_change(
            interaction, panel, "Publicação", self.panel.channel_id, channel.id
        )
        await _render_panel_edit(interaction, panel, self.on_back)


# ============================ editor do formulário =========================


def form_editor_embed(panel: TicketPanel, fields: list[TicketPanelFormField]) -> discord.Embed:
    embed = discord.Embed(
        title=f"📝 Formulário — {panel.name}",
        description=(
            "Perguntas feitas num modal antes do ticket ser criado. As respostas ficam "
            "salvas, aparecem no canal do ticket e vão pra auditoria.\n"
            f"Status: {_bool_label(panel.form_enabled)} · "
            f"{len(fields)}/{MAX_FORM_FIELDS} pergunta(s)."
        ),
        color=EMBED_COLOR_DEFAULT,
    )
    for field in fields:
        embed.add_field(
            name=f"{field.position + 1}. {field.label}",
            value=(
                f"{FORM_FIELD_STYLES.get(field.style, field.style)} · "
                f"{'obrigatória' if field.required else 'opcional'}"
            ),
            inline=False,
        )
    if not fields:
        embed.add_field(
            name="Nenhuma pergunta",
            value="Use **➕ Adicionar pergunta** pra criar a primeira.",
            inline=False,
        )
    return embed


async def _render_form_editor(
    interaction: discord.Interaction, panel: TicketPanel, on_back: Any = None
) -> None:
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    panel = await bot.ticket_panel_service.get_panel(panel.id) or panel
    fields = await bot.ticket_panel_service.list_form_fields(panel.id)
    embed = form_editor_embed(panel, fields)
    view = TicketPanelFormView(panel, fields, on_back)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embed=embed, view=view)
    else:
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class TicketPanelFormView(SafeView):
    def __init__(
        self, panel: TicketPanel, fields: list[TicketPanelFormField], on_back: Any = None
    ) -> None:
        super().__init__(timeout=300)
        self.panel = panel
        self.on_back = on_back
        if fields:
            self.add_item(_FormFieldSelect(panel, fields, on_back))
        self.toggle_form.label = (
            "🚫 Desativar formulário" if panel.form_enabled else "✅ Ativar formulário"
        )
        self.add_item(_BackToPanelEditButton(panel, on_back))

    @discord.ui.button(label="➕ Adicionar pergunta", style=discord.ButtonStyle.success, row=1)
    async def add_field(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await interaction.response.send_modal(_FormFieldModal(self.panel, None, self.on_back))

    @discord.ui.button(label="✅ Ativar formulário", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_form(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        before = self.panel.form_enabled
        panel = await bot.ticket_panel_service.update_panel(
            self.panel.id, form_enabled=not before
        )
        await _log_panel_change(
            interaction, panel, "Formulário", _bool_label(before), _bool_label(not before)
        )
        await _render_form_editor(interaction, panel, self.on_back)


class _FormFieldSelect(discord.ui.Select[Any]):
    def __init__(
        self, panel: TicketPanel, fields: list[TicketPanelFormField], on_back: Any
    ) -> None:
        super().__init__(
            placeholder="Selecione uma pergunta pra editar/remover...",
            options=[
                discord.SelectOption(
                    label=f"{f.position + 1}. {f.label}"[:100],
                    value=str(f.id),
                    description=FORM_FIELD_STYLES.get(f.style, f.style),
                )
                for f in fields
            ][:25],
            min_values=1,
            max_values=1,
        )
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        field_id = uuid.UUID(self.values[0])
        fields = await bot.ticket_panel_service.list_form_fields(self.panel.id)
        field = next((f for f in fields if f.id == field_id), None)
        if field is None:
            await interaction.response.send_message("Pergunta não encontrada.", ephemeral=True)
            return
        view = SafeView(timeout=180)
        view.add_item(_EditFormFieldButton(self.panel, field, self.on_back))
        view.add_item(_DeleteFormFieldButton(self.panel, field, self.on_back))
        view.add_item(_BackToFormButton(self.panel, self.on_back))
        await interaction.response.edit_message(
            content=f"**{field.label}** — o que deseja fazer?", embed=None, view=view
        )


class _EditFormFieldButton(discord.ui.Button[Any]):
    def __init__(self, panel: TicketPanel, field: TicketPanelFormField, on_back: Any) -> None:
        super().__init__(label="✏️ Editar", style=discord.ButtonStyle.primary)
        self.panel = panel
        self.field = field
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            _FormFieldModal(self.panel, self.field, self.on_back)
        )


class _DeleteFormFieldButton(discord.ui.Button[Any]):
    def __init__(self, panel: TicketPanel, field: TicketPanelFormField, on_back: Any) -> None:
        super().__init__(label="🗑️ Remover", style=discord.ButtonStyle.danger)
        self.panel = panel
        self.field = field
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        await bot.ticket_panel_service.delete_form_field(self.field.id)
        await _log_panel_change(
            interaction, self.panel, "Pergunta removida", self.field.label, "—"
        )
        await _render_form_editor(interaction, self.panel, self.on_back)


class _BackToFormButton(discord.ui.Button[Any]):
    def __init__(self, panel: TicketPanel, on_back: Any) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary)
        self.panel = panel
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await _render_form_editor(interaction, self.panel, self.on_back)


def _parse_yes_no(raw: str, *, default: bool) -> bool:
    value = raw.strip().lower()
    if value in ("sim", "s", "yes", "y", "true", "1"):
        return True
    if value in ("nao", "não", "n", "no", "false", "0"):
        return False
    return default


class _FormFieldModal(discord.ui.Modal):
    def __init__(
        self, panel: TicketPanel, field: TicketPanelFormField | None, on_back: Any
    ) -> None:
        super().__init__(title="Pergunta do formulário")
        self.panel = panel
        self.field = field
        self.on_back = on_back
        self.label_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Pergunta",
            placeholder="Ex: Qual o seu nick no jogo?",
            default=field.label if field else "",
            max_length=45,
        )
        self.placeholder_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Dica dentro do campo (opcional)",
            default=(field.placeholder if field else "") or "",
            required=False,
            max_length=100,
        )
        self.style_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Tipo: curta ou longa",
            default="longa" if field is not None and field.style == "long" else "curta",
            max_length=10,
        )
        self.required_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Obrigatória? sim ou não",
            default="sim" if field is None or field.required else "não",
            max_length=5,
        )
        self.add_item(self.label_input)
        self.add_item(self.placeholder_input)
        self.add_item(self.style_input)
        self.add_item(self.required_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        label = str(self.label_input.value).strip()
        if not label:
            await interaction.response.send_message(
                "A pergunta não pode ficar vazia.", ephemeral=True
            )
            return
        style = "long" if str(self.style_input.value).strip().lower().startswith("l") else "short"
        required = _parse_yes_no(str(self.required_input.value), default=True)
        placeholder = str(self.placeholder_input.value).strip() or None

        if self.field is None:
            try:
                await bot.ticket_panel_service.add_form_field(
                    self.panel.id,
                    label=label,
                    style=style,
                    required=required,
                    placeholder=placeholder,
                )
            except TicketPanelError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
            await _log_panel_change(interaction, self.panel, "Pergunta adicionada", "—", label)
        else:
            await bot.ticket_panel_service.update_form_field(
                self.field.id,
                label=label,
                style=style,
                required=required,
                placeholder=placeholder,
            )
            await _log_panel_change(
                interaction, self.panel, "Pergunta editada", self.field.label, label
            )
        await _render_form_editor(interaction, self.panel, self.on_back)
