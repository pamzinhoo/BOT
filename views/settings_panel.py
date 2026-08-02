from __future__ import annotations

import enum
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import discord
from views.base_view import SafeView

from database.models.audit_log import AuditLogCategory
from utils.model_defaults import column_default


class FieldKind(enum.Enum):
    CHANNEL = "channel"
    ROLE = "role"
    ROLE_MULTI = "role_multi"
    NUMBER = "number"
    BOOL = "bool"
    CHOICE = "choice"
    TEXT = "text"


@dataclass
class SettingsField:
    attr: str
    label: str
    kind: FieldKind
    model: type = object  # model dono da coluna `attr` — usado só pra resolver o valor padrão no reset
    choices: list[tuple[str, str]] | None = None  # (value, label), so kind == CHOICE
    channel_types: list[discord.ChannelType] | None = None  # so kind == CHANNEL
    allow_clear: bool = True  # so kind == NUMBER — False pra coluna NOT NULL (nao pode virar None)
    # validador opcional (so usado por kind TEXT/CHOICE hoje) — recebe o
    # objeto de settings ATUAL da guild (antes da mudança) e o valor bruto
    # submetido, devolve o valor NORMALIZADO a persistir, ou levanta
    # ValueError com mensagem pronta pra exibir ao usuário (bloqueia o save).
    # Default None em todo domínio existente — comportamento 100% inalterado
    # pra quem não define validator.
    validator: Callable[[Any, str], str] | None = None


def category_defaults(fields: list[SettingsField]) -> dict[str, Any]:
    """Valores padrão de cada campo da categoria, lidos direto dos models
    (mesmos usados no primeiro get_or_create de uma guild)."""
    return {field.attr: column_default(field.model, field.attr) for field in fields}


GetSettings = Callable[[int], Awaitable[Any]]
UpdateSettings = Callable[..., Awaitable[Any]]
OnBack = Callable[[discord.Interaction], Awaitable[None]]


def _format_value(field: SettingsField, raw: object) -> str:
    if field.kind == FieldKind.BOOL:
        return "✅ Ativado" if raw else "❌ Desativado"
    if field.kind == FieldKind.ROLE_MULTI:
        role_ids = raw or []
        if not role_ids:
            return "— (usa o padrão do bot)"
        return ", ".join(f"<@&{rid}>" for rid in role_ids)
    if raw is None:
        return "—"
    if field.kind == FieldKind.CHANNEL:
        return f"<#{raw}>"
    if field.kind == FieldKind.ROLE:
        return f"<@&{raw}>"
    if field.kind == FieldKind.CHOICE:
        label = next((lbl for value, lbl in (field.choices or []) if str(value) == str(raw)), None)
        return label or str(raw)
    if field.kind == FieldKind.TEXT:
        text = str(raw)
        return text if len(text) <= 200 else f"{text[:200]}…"
    return str(raw)


def _category_label(title: str) -> str:
    """Tira o emoji de prefixo do titulo do painel (ex: '🎫 Tickets' -> 'Tickets')
    pra usar como valor de filtro em /config history."""
    parts = title.split(" ", 1)
    return parts[1] if len(parts) > 1 else title


async def _log_change(
    interaction: discord.Interaction,
    parent: "DomainSettingsView",
    field: SettingsField,
    before_raw: object,
    after_raw: object,
) -> None:
    from core.bot import LimerenceBot  # import tardio evita ciclo

    assert interaction.guild_id is not None
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    await bot.audit_log_service.record_config_change(
        guild_id=interaction.guild_id,
        actor_id=interaction.user.id,
        actor_name=str(interaction.user),
        config_category=_category_label(parent.title),
        config_name=field.label,
        old_value=_format_value(field, before_raw),
        new_value=_format_value(field, after_raw),
    )


def build_domain_embed(title: str, fields: list[SettingsField], settings: object) -> discord.Embed:
    embed = discord.Embed(title=title)
    for field in fields:
        raw = getattr(settings, field.attr)
        embed.add_field(name=field.label, value=_format_value(field, raw), inline=True)
    embed.set_footer(text="Selecione um item abaixo para editar.")
    return embed


class DomainSettingsView(SafeView):
    """Painel generico de configuracao de um dominio (Tickets/Dashboard/Ranking/...).
    Nao-persistente (timeout=300) — utilitario de admin aberto sob demanda."""

    def __init__(
        self,
        *,
        title: str,
        fields: list[SettingsField],
        get_settings: GetSettings,
        update_settings: UpdateSettings,
        on_back: OnBack,
    ) -> None:
        super().__init__(timeout=300)
        self.title = title
        self.fields = fields
        self.get_settings = get_settings
        self.update_settings = update_settings
        self.on_back = on_back
        self.add_item(_FieldPickSelect(self))
        self.add_item(_ResetCategoryButton(self))
        self.add_item(_BackToMenuButton(on_back))

    async def render(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        settings = await self.get_settings(interaction.guild_id)
        await interaction.response.edit_message(
            content=None,
            embed=build_domain_embed(self.title, self.fields, settings),
            view=DomainSettingsView(
                title=self.title,
                fields=self.fields,
                get_settings=self.get_settings,
                update_settings=self.update_settings,
                on_back=self.on_back,
            ),
        )


class _FieldPickSelect(discord.ui.Select[DomainSettingsView]):
    def __init__(self, parent: DomainSettingsView) -> None:
        options = [
            discord.SelectOption(label=field.label, value=field.attr) for field in parent.fields
        ]
        super().__init__(placeholder="O que deseja configurar?", options=options, min_values=1, max_values=1)
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        field = next(f for f in self.parent_view.fields if f.attr == self.values[0])
        parent = self.parent_view

        if field.kind == FieldKind.BOOL:
            settings = await parent.get_settings(interaction.guild_id)
            before = getattr(settings, field.attr)
            new_value = not before
            await parent.update_settings(interaction.guild_id, **{field.attr: new_value})
            await _log_change(interaction, parent, field, before, new_value)
            await parent.render(interaction)
            return

        if field.kind == FieldKind.NUMBER:
            await interaction.response.send_modal(_NumberModal(parent, field))
            return

        if field.kind == FieldKind.TEXT:
            await interaction.response.send_modal(_TextModal(parent, field))
            return

        sub_view = SafeView(timeout=180)
        if field.kind == FieldKind.CHANNEL:
            sub_view.add_item(_ChannelPicker(parent, field))
        elif field.kind == FieldKind.ROLE:
            sub_view.add_item(_RolePicker(parent, field))
        elif field.kind == FieldKind.ROLE_MULTI:
            sub_view.add_item(_RoleMultiPicker(parent, field))
        elif field.kind == FieldKind.CHOICE:
            sub_view.add_item(_ChoicePicker(parent, field))
        sub_view.add_item(_BackToDomainButton(parent))

        await interaction.response.edit_message(
            content=f"**{field.label}** — selecione abaixo:", embed=None, view=sub_view
        )


class _ChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, parent: DomainSettingsView, field: SettingsField) -> None:
        super().__init__(
            placeholder=f"Selecionar: {field.label}",
            channel_types=field.channel_types or [discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        self.parent_view = parent
        self.field = field

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        settings = await self.parent_view.get_settings(interaction.guild_id)
        before = getattr(settings, self.field.attr)
        after = self.values[0].id
        await self.parent_view.update_settings(interaction.guild_id, **{self.field.attr: after})
        await _log_change(interaction, self.parent_view, self.field, before, after)
        await self.parent_view.render(interaction)


class _RolePicker(discord.ui.RoleSelect):
    def __init__(self, parent: DomainSettingsView, field: SettingsField) -> None:
        super().__init__(placeholder=f"Selecionar: {field.label}", min_values=1, max_values=1)
        self.parent_view = parent
        self.field = field

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        settings = await self.parent_view.get_settings(interaction.guild_id)
        before = getattr(settings, self.field.attr)
        after = self.values[0].id
        await self.parent_view.update_settings(interaction.guild_id, **{self.field.attr: after})
        await _log_change(interaction, self.parent_view, self.field, before, after)
        await self.parent_view.render(interaction)


class _RoleMultiPicker(discord.ui.RoleSelect):
    def __init__(self, parent: DomainSettingsView, field: SettingsField) -> None:
        super().__init__(
            placeholder=f"Selecionar cargos: {field.label} (vazio = usa o padrão do bot)",
            min_values=0,
            max_values=25,
        )
        self.parent_view = parent
        self.field = field

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        settings = await self.parent_view.get_settings(interaction.guild_id)
        before = list(getattr(settings, self.field.attr) or [])
        role_ids = [role.id for role in self.values]
        await self.parent_view.update_settings(interaction.guild_id, **{self.field.attr: role_ids})
        if sorted(before) != sorted(role_ids):
            await _log_change(interaction, self.parent_view, self.field, before, role_ids)
        await self.parent_view.render(interaction)


class _ChoicePicker(discord.ui.Select[Any]):
    def __init__(self, parent: DomainSettingsView, field: SettingsField) -> None:
        options = [
            discord.SelectOption(label=label, value=value) for value, label in (field.choices or [])
        ]
        super().__init__(placeholder=f"Selecionar: {field.label}", options=options, min_values=1, max_values=1)
        self.parent_view = parent
        self.field = field

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        settings = await self.parent_view.get_settings(interaction.guild_id)
        before = getattr(settings, self.field.attr)
        after = self.values[0]
        if self.field.validator is not None:
            try:
                after = self.field.validator(settings, after)
            except ValueError as exc:
                await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                return
        await self.parent_view.update_settings(interaction.guild_id, **{self.field.attr: after})
        await _log_change(interaction, self.parent_view, self.field, before, after)
        await self.parent_view.render(interaction)


class _TextModal(discord.ui.Modal):
    value_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Texto",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
    )

    def __init__(self, parent: DomainSettingsView, field: SettingsField) -> None:
        super().__init__(title=field.label[:45])
        self.parent_view = parent
        self.field = field
        self.value_input.label = field.label[:45]
        self.value_input.placeholder = "Deixe vazio para usar a mensagem padrão"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        raw = str(self.value_input.value).strip()
        settings = await self.parent_view.get_settings(interaction.guild_id)
        before = getattr(settings, self.field.attr)
        after: str | None = raw or None
        if after is not None and self.field.validator is not None:
            try:
                after = self.field.validator(settings, after)
            except ValueError as exc:
                await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                return
        await self.parent_view.update_settings(interaction.guild_id, **{self.field.attr: after})
        await _log_change(interaction, self.parent_view, self.field, before, after)
        await self.parent_view.render(interaction)


class _BackToDomainButton(discord.ui.Button[Any]):
    def __init__(self, parent: DomainSettingsView) -> None:
        super().__init__(label="Voltar", style=discord.ButtonStyle.secondary)
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.parent_view.render(interaction)


class _ResetCategoryButton(discord.ui.Button[Any]):
    def __init__(self, parent: DomainSettingsView) -> None:
        super().__init__(label="🔄 Restaurar padrão", style=discord.ButtonStyle.danger, row=1)
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        parent = self.parent_view
        settings = await parent.get_settings(interaction.guild_id)
        defaults = category_defaults(parent.fields)
        changed = [f for f in parent.fields if getattr(settings, f.attr) != defaults[f.attr]]

        embed = discord.Embed(title=f"🔄 Restaurar padrão — {parent.title}")
        if changed:
            embed.description = (
                "Isso vai restaurar **apenas esta categoria** para os valores padrão. "
                "As outras categorias não são afetadas."
            )
            for field in changed:
                before = _format_value(field, getattr(settings, field.attr))
                after = _format_value(field, defaults[field.attr])
                embed.add_field(name=field.label, value=f"{before} → {after}", inline=False)
        else:
            embed.description = "Esta categoria já está nos valores padrão — nada para restaurar."

        await interaction.response.edit_message(
            content=None, embed=embed, view=_ResetCategoryConfirmView(parent, defaults, enabled=bool(changed))
        )


class _ResetCategoryConfirmView(SafeView):
    """Confirmação do reset de UMA categoria. So quem abriu o painel pode confirmar."""

    def __init__(self, parent: DomainSettingsView, defaults: dict[str, Any], *, enabled: bool) -> None:
        super().__init__(timeout=120)
        self.parent_view = parent
        self.defaults = defaults
        confirm = _ConfirmCategoryResetButton(parent, defaults)
        confirm.disabled = not enabled
        self.add_item(confirm)
        self.add_item(_CancelCategoryResetButton(parent))


class _ConfirmCategoryResetButton(discord.ui.Button[Any]):
    def __init__(self, parent: DomainSettingsView, defaults: dict[str, Any]) -> None:
        super().__init__(label="Confirmar restauração", style=discord.ButtonStyle.danger)
        self.parent_view = parent
        self.defaults = defaults

    async def callback(self, interaction: discord.Interaction) -> None:
        from core.bot import LimerenceBot  # import tardio evita ciclo

        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        parent = self.parent_view

        settings = await parent.get_settings(interaction.guild_id)
        changed_count = sum(
            1 for field in parent.fields if getattr(settings, field.attr) != self.defaults[field.attr]
        )
        await parent.update_settings(interaction.guild_id, **self.defaults)
        await bot.audit_log_service.record(
            guild_id=interaction.guild_id,
            category=AuditLogCategory.SERVER_CONFIG,
            action="Categoria restaurada para padrão",
            executor_id=interaction.user.id,
            executor_name=str(interaction.user),
            config_category=_category_label(parent.title),
            config_name="Reset de Categoria",
            old_value=f"{changed_count} configuração(ões) personalizada(s)",
            new_value="Restaurado para o padrão",
        )
        await parent.render(interaction)


class _CancelCategoryResetButton(discord.ui.Button[Any]):
    def __init__(self, parent: DomainSettingsView) -> None:
        super().__init__(label="Cancelar", style=discord.ButtonStyle.secondary)
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.parent_view.render(interaction)


class _BackToMenuButton(discord.ui.Button[Any]):
    def __init__(self, on_back: OnBack) -> None:
        super().__init__(label="◀ Menu principal", style=discord.ButtonStyle.secondary, row=4)
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.on_back(interaction)


class _NumberModal(discord.ui.Modal):
    value_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Valor", placeholder="Ex: 15 (vazio = sem limite)", required=False, max_length=6
    )

    def __init__(self, parent: DomainSettingsView, field: SettingsField) -> None:
        super().__init__(title=field.label)
        self.parent_view = parent
        self.field = field
        self.value_input.label = field.label
        self.value_input.required = not field.allow_clear
        self.value_input.placeholder = "Ex: 15" if not field.allow_clear else "Ex: 15 (vazio = sem limite)"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        raw = str(self.value_input.value).strip()
        settings = await self.parent_view.get_settings(interaction.guild_id)
        before = getattr(settings, self.field.attr)
        if not raw:
            if not self.field.allow_clear:
                await interaction.response.send_message(
                    "Esse campo não pode ficar vazio — digite um número.", ephemeral=True
                )
                return
            after = None
            await self.parent_view.update_settings(interaction.guild_id, **{self.field.attr: after})
        elif raw.isdigit():
            after = int(raw)
            await self.parent_view.update_settings(interaction.guild_id, **{self.field.attr: after})
        else:
            await interaction.response.send_message("Digite um número inteiro válido.", ephemeral=True)
            return
        await _log_change(interaction, self.parent_view, self.field, before, after)
        await self.parent_view.render(interaction)
