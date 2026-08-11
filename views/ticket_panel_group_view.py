from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import discord

from database.models.ticket_panel import TicketPanel
from database.models.ticket_panel_group import MAX_GROUP_PANELS, TicketPanelGroup
from services.ticket_panel_service import TicketPanelError
from utils.constants import EMBED_COLOR_DEFAULT, EMBED_COLOR_WARNING
from views.base_view import SafeView

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_TEXT = [discord.ChannelType.text, discord.ChannelType.news]


async def _log_group_change(
    interaction: discord.Interaction,
    group: TicketPanelGroup,
    field_label: str,
    before: object,
    after: object,
) -> None:
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    if interaction.guild_id is None:
        return
    await bot.audit_log_service.record_config_change(
        guild_id=interaction.guild_id,
        actor_id=interaction.user.id,
        actor_name=str(interaction.user),
        config_category="Tickets",
        config_name=f"Combo {group.name} — {field_label}",
        old_value=str(before) if before not in (None, "") else "—",
        new_value=str(after) if after not in (None, "") else "—",
    )


# ============================= lista de combos ==============================


def groups_list_embed(groups: list[TicketPanelGroup]) -> discord.Embed:
    embed = discord.Embed(
        title="📦 Combos de Painéis",
        description=(
            "Um combo publica vários painéis já criados numa mensagem só — a "
            "embed (banner/logo/título/cor) vem do painel principal, e cada "
            "painel do combo vira um botão ao lado dos outros."
        ),
        color=EMBED_COLOR_DEFAULT,
    )
    if not groups:
        embed.add_field(
            name="Nenhum combo criado ainda",
            value="Use **➕ Criar Combo** (precisa de pelo menos 2 painéis já cadastrados).",
            inline=False,
        )
        return embed
    for group in groups:
        published = f"<#{group.channel_id}>" if group.channel_id else "não publicado"
        embed.add_field(
            name=group.name, value=f"{len(group.panel_ids)} painel(éis) · {published}", inline=True
        )
    return embed


async def render_groups_list(interaction: discord.Interaction, on_back: Any = None) -> None:
    assert interaction.guild_id is not None
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    groups = await bot.ticket_panel_service.list_groups(interaction.guild_id)
    panels = await bot.ticket_panel_service.list_panels(interaction.guild_id)
    view = TicketPanelGroupsListView(groups, panels, on_back)
    embed = groups_list_embed(groups)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embed=embed, view=view)
    else:
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class TicketPanelGroupsListView(SafeView):
    def __init__(
        self, groups: list[TicketPanelGroup], panels: list[TicketPanel], on_back: Any = None
    ) -> None:
        super().__init__(timeout=300)
        self.on_back = on_back
        if groups:
            self.add_item(_GroupSelect(groups, on_back))
        self.add_item(_CreateGroupButton(panels, on_back))
        self.add_item(_BackToTicketsMenuButton(on_back))


class _GroupSelect(discord.ui.Select[Any]):
    def __init__(self, groups: list[TicketPanelGroup], on_back: Any) -> None:
        options = [
            discord.SelectOption(label=group.name[:100], value=str(group.id))
            for group in groups
        ][:25]
        super().__init__(
            placeholder="Selecione um combo pra editar...", options=options, min_values=1, max_values=1
        )
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        group = await bot.ticket_panel_service.get_group(uuid.UUID(self.values[0]))
        if group is None or group.guild_id != interaction.guild_id:
            await interaction.response.send_message("Combo não encontrado.", ephemeral=True)
            return
        await _render_group_edit(interaction, group, self.on_back)


class _CreateGroupButton(discord.ui.Button[Any]):
    def __init__(self, panels: list[TicketPanel], on_back: Any) -> None:
        super().__init__(label="➕ Criar Combo", style=discord.ButtonStyle.success)
        self.panels = panels
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        if len(self.panels) < 2:
            await interaction.response.send_message(
                "Você precisa de pelo menos 2 painéis criados (em 📋 Painéis de Tickets) "
                "antes de montar um combo.",
                ephemeral=True,
            )
            return
        view = SafeView(timeout=180)
        view.add_item(_GroupPanelMultiSelect(self.panels, self.on_back))
        view.add_item(_BackToGroupsListButton(self.on_back))
        await interaction.response.edit_message(
            content=(
                f"Escolha de 2 a {MAX_GROUP_PANELS} painéis pra juntar num combo "
                "(cada um vira um botão na mesma mensagem):"
            ),
            embed=None,
            view=view,
        )


class _BackToTicketsMenuButton(discord.ui.Button[Any]):
    def __init__(self, on_back: Any) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary)
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        from views.ticket_panels_view import render_tickets_menu

        await render_tickets_menu(interaction, self.on_back)


class _BackToGroupsListButton(discord.ui.Button[Any]):
    def __init__(self, on_back: Any) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=4)
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await render_groups_list(interaction, self.on_back)


# ============================ fluxo de criacao ===============================


class _GroupPanelMultiSelect(discord.ui.Select[Any]):
    def __init__(self, panels: list[TicketPanel], on_back: Any) -> None:
        options = [
            discord.SelectOption(label=panel.name[:100], value=str(panel.id))
            for panel in panels
        ][:25]
        super().__init__(
            placeholder="Painéis do combo...",
            options=options,
            min_values=2,
            max_values=min(len(options), MAX_GROUP_PANELS),
        )
        self.panels = panels
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        by_id = {str(panel.id): panel for panel in self.panels}
        chosen = [by_id[value] for value in self.values if value in by_id]
        view = SafeView(timeout=180)
        view.add_item(_GroupPrimarySelect(chosen, self.on_back))
        view.add_item(_BackToGroupsListButton(self.on_back))
        await interaction.response.edit_message(
            content=(
                "Qual painel define a aparência da mensagem (título/descrição/banner/logo/cor)? "
                "Os outros só entram como botão extra."
            ),
            embed=None,
            view=view,
        )


class _GroupPrimarySelect(discord.ui.Select[Any]):
    def __init__(self, chosen: list[TicketPanel], on_back: Any) -> None:
        options = [
            discord.SelectOption(label=panel.name[:100], value=str(panel.id)) for panel in chosen
        ]
        super().__init__(placeholder="Painel principal...", options=options, min_values=1, max_values=1)
        self.chosen = chosen
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        primary_id = self.values[0]
        ordered = [p for p in self.chosen if str(p.id) == primary_id] + [
            p for p in self.chosen if str(p.id) != primary_id
        ]
        await interaction.response.send_modal(_GroupNameModal(ordered, self.on_back))


class _GroupNameModal(discord.ui.Modal, title="Nome do combo"):
    name_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Nome (só pra identificar no /config)",
        placeholder="Ex: Painel principal de tickets",
        max_length=100,
    )

    def __init__(self, ordered_panels: list[TicketPanel], on_back: Any) -> None:
        super().__init__()
        self.ordered_panels = ordered_panels
        self.on_back = on_back
        self.name_input.default = " + ".join(p.name for p in ordered_panels)[:100]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        try:
            group = await bot.ticket_panel_service.create_group(
                interaction.guild_id,
                str(self.name_input.value),
                [p.id for p in self.ordered_panels],
            )
        except TicketPanelError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await bot.audit_log_service.record_config_change(
            guild_id=interaction.guild_id,
            actor_id=interaction.user.id,
            actor_name=str(interaction.user),
            config_category="Tickets",
            config_name="Combo criado",
            old_value="—",
            new_value=f"{group.name} ({len(group.panel_ids)} painéis)",
        )
        await _render_group_edit(interaction, group, self.on_back)


# ============================== editor do combo ==============================


async def group_edit_embed(bot: LimerenceBot, group: TicketPanelGroup) -> discord.Embed:
    panels = await bot.ticket_panel_service.get_group_panels(group)
    embed = discord.Embed(title=f"📦 {group.name}", color=EMBED_COLOR_WARNING)
    embed.add_field(
        name="Publicado em", value=f"<#{group.channel_id}>" if group.channel_id else "—"
    )
    embed.add_field(
        name="Painel principal (define a embed)",
        value=panels[0].name if panels else "*(nenhum painel válido)*",
    )
    embed.add_field(
        name="Botões do combo",
        value=(
            "\n".join(f"• {p.name}" for p in panels) if panels else "*(nenhum painel válido)*"
        ),
        inline=False,
    )
    return embed


async def _render_group_edit(
    interaction: discord.Interaction, group: TicketPanelGroup, on_back: Any = None
) -> None:
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    embed = await group_edit_embed(bot, group)
    view = TicketPanelGroupEditView(group, on_back)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embed=embed, view=view)
    else:
        await interaction.response.edit_message(content=None, embed=embed, view=view)
    if group.channel_id is not None and group.message_id is not None:
        await bot.ticket_panel_service.refresh_group(group.id)


class TicketPanelGroupEditView(SafeView):
    def __init__(self, group: TicketPanelGroup, on_back: Any = None) -> None:
        super().__init__(timeout=300)
        self.group = group
        self.on_back = on_back

    @discord.ui.button(label="✏️ Nome", style=discord.ButtonStyle.primary, row=0)
    async def name_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await interaction.response.send_modal(_GroupRenameModal(self.group, self.on_back))

    @discord.ui.button(label="📢 Publicar", style=discord.ButtonStyle.success, row=0)
    async def publish_button(
        self, interaction: discord.Interaction, _b: discord.ui.Button
    ) -> None:
        view = SafeView(timeout=180)
        view.add_item(_PublishGroupChannelPicker(self.group, self.on_back))
        view.add_item(_BackToGroupEditButton(self.group, self.on_back))
        await interaction.response.edit_message(
            content="Em qual canal publicar este combo?", embed=None, view=view
        )

    @discord.ui.button(label="🔄 Atualizar", style=discord.ButtonStyle.secondary, row=0)
    async def refresh_button(
        self, interaction: discord.Interaction, _b: discord.ui.Button
    ) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        if self.group.channel_id is None:
            await interaction.response.send_message(
                "Este combo ainda não foi publicado em nenhum canal.", ephemeral=True
            )
            return
        group = await bot.ticket_panel_service.refresh_group(self.group.id)
        await _render_group_edit(interaction, group or self.group, self.on_back)

    @discord.ui.button(label="🗑️ Despublicar", style=discord.ButtonStyle.secondary, row=1)
    async def unpublish_button(
        self, interaction: discord.Interaction, _b: discord.ui.Button
    ) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        if self.group.channel_id is None:
            await interaction.response.send_message("Este combo não está publicado.", ephemeral=True)
            return
        group = await bot.ticket_panel_service.unpublish_group(self.group.id)
        await _log_group_change(interaction, group, "Publicação", "publicado", "despublicado")
        await _render_group_edit(interaction, group, self.on_back)

    @discord.ui.button(label="❌ Excluir", style=discord.ButtonStyle.danger, row=1)
    async def delete_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        view = SafeView(timeout=60)
        view.add_item(_ConfirmDeleteGroupButton(self.group, self.on_back))
        view.add_item(_BackToGroupEditButton(self.group, self.on_back))
        await interaction.response.edit_message(
            content=(
                f"Excluir o combo **{self.group.name}**? A mensagem publicada é apagada — os "
                "painéis usados nele continuam existindo normalmente."
            ),
            embed=None,
            view=view,
        )

    @discord.ui.button(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await render_groups_list(interaction, self.on_back)


class _BackToGroupEditButton(discord.ui.Button[Any]):
    def __init__(self, group: TicketPanelGroup, on_back: Any) -> None:
        super().__init__(label="◀ Voltar", style=discord.ButtonStyle.secondary, row=4)
        self.group = group
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        group = await bot.ticket_panel_service.get_group(self.group.id) or self.group
        await _render_group_edit(interaction, group, self.on_back)


class _GroupRenameModal(discord.ui.Modal, title="Nome do combo"):
    name_input: discord.ui.TextInput[Any] = discord.ui.TextInput(label="Nome", max_length=100)

    def __init__(self, group: TicketPanelGroup, on_back: Any) -> None:
        super().__init__()
        self.group = group
        self.on_back = on_back
        self.name_input.default = group.name

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        new_name = str(self.name_input.value).strip()
        if not new_name:
            await interaction.response.send_message("O nome não pode ficar vazio.", ephemeral=True)
            return
        before = self.group.name
        group = await bot.ticket_panel_service.update_group(self.group.id, name=new_name)
        await _log_group_change(interaction, group, "Nome", before, new_name)
        await _render_group_edit(interaction, group, self.on_back)


class _PublishGroupChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, group: TicketPanelGroup, on_back: Any) -> None:
        super().__init__(
            placeholder="Canal onde o combo será publicado",
            channel_types=_TEXT,
            min_values=1,
            max_values=1,
        )
        self.group = group
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
            group = await bot.ticket_panel_service.publish_group(self.group.id, channel)
        except TicketPanelError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await _log_group_change(interaction, group, "Publicação", self.group.channel_id, channel.id)
        await _render_group_edit(interaction, group, self.on_back)


class _ConfirmDeleteGroupButton(discord.ui.Button[Any]):
    def __init__(self, group: TicketPanelGroup, on_back: Any) -> None:
        super().__init__(label="Confirmar exclusão", style=discord.ButtonStyle.danger)
        self.group = group
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        name = self.group.name
        await bot.ticket_panel_service.delete_group(self.group.id)
        await bot.audit_log_service.record_config_change(
            guild_id=interaction.guild_id,
            actor_id=interaction.user.id,
            actor_name=str(interaction.user),
            config_category="Tickets",
            config_name="Combo excluído",
            old_value=name,
            new_value="—",
        )
        await render_groups_list(interaction, self.on_back)
