from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import discord
from views.base_view import SafeView

from database.models.audit_log import AuditLogCategory
from database.models.giveaway import Giveaway, GiveawayPrizeType, GiveawayStatus
from services.giveaway_service import InvalidWinnersCountError
from utils.constants import EMBED_COLOR_DEFAULT, EMBED_COLOR_PURPLE
from utils.time import InvalidDurationError, parse_duration
from views.embeds import giveaway_panel_embed

if TYPE_CHECKING:
    from core.bot import LimerenceBot


def giveaway_menu_embed() -> discord.Embed:
    return discord.Embed(
        title="🎉 Sorteios",
        description=(
            "Crie sorteios com painel fixo no canal escolhido. Participação por botão, "
            "restrição por cargo opcional e prêmio em cargo ou texto personalizado."
        ),
        color=EMBED_COLOR_DEFAULT,
    )


class GiveawayMenuView(SafeView):
    def __init__(self, on_back: Any) -> None:
        super().__init__(timeout=300)
        self.on_back = on_back
        self.add_item(_BackButton(on_back, label="◀ Menu principal", row=4))

    @discord.ui.button(label="➕ Criar Sorteio", style=discord.ButtonStyle.success)
    async def create_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content="**Passo 1/4** — Escolha o canal onde o sorteio será enviado:",
            embed=None,
            view=_ChannelPickView(self.on_back),
        )

    @discord.ui.button(label="📋 Sorteios Ativos", style=discord.ButtonStyle.secondary)
    async def list_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer()
        assert interaction.guild_id is not None
        bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]
        giveaways = await bot.giveaway_service.list_by_guild(interaction.guild_id)
        open_giveaways = [g for g in giveaways if g.status == GiveawayStatus.OPEN]
        await interaction.edit_original_response(
            content=None,
            embed=_active_giveaways_embed(open_giveaways),
            view=GiveawayMenuView(self.on_back),
        )


def _active_giveaways_embed(giveaways: list[Giveaway]) -> discord.Embed:
    embed = discord.Embed(title="📋 Sorteios Ativos", color=EMBED_COLOR_PURPLE)
    if not giveaways:
        embed.description = "Nenhum sorteio ativo no momento."
        return embed
    for giveaway in giveaways:
        embed.add_field(
            name=giveaway.title,
            value=(
                f"Canal: <#{giveaway.channel_id}>\n"
                f"Encerra: {discord.utils.format_dt(giveaway.expires_at, style='R')}"
            ),
            inline=False,
        )
    return embed


class _BackButton(discord.ui.Button[Any]):
    def __init__(self, on_back: Any, *, label: str = "Voltar", row: int | None = None) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=row)
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.on_back(interaction)


async def _back_to_giveaway_menu(on_back: Any, interaction: discord.Interaction) -> None:
    await interaction.response.edit_message(
        content=None, embed=giveaway_menu_embed(), view=GiveawayMenuView(on_back)
    )


@dataclass
class _GiveawayDraft:
    on_back: Any
    channel_id: int
    title: str = ""
    description: str | None = None
    duration_text: str = "24h"
    winners_count: int = 1
    allowed_role_ids: list[int] = field(default_factory=list)


class _ChannelPickView(SafeView):
    def __init__(self, on_back: Any) -> None:
        super().__init__(timeout=300)
        self.on_back = on_back
        self.add_item(_ChannelPicker(on_back))
        self.add_item(_BackButton(lambda i: _back_to_giveaway_menu(on_back, i)))


class _ChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, on_back: Any) -> None:
        super().__init__(
            placeholder="Escolha o canal do sorteio",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        self.on_back = on_back

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(_GiveawayCreateModal(self.on_back, self.values[0].id))


class _GiveawayCreateModal(discord.ui.Modal, title="Criar Sorteio"):
    titulo: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Título", max_length=256, required=True
    )
    descricao: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Descrição (ex: Quem ganhar recebe...)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )
    duracao: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Duração (ex: 24h, 30m, 7d)", required=True, max_length=10, default="24h"
    )
    vencedores: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Quantidade de vencedores", required=True, max_length=3, default="1"
    )

    def __init__(self, on_back: Any, channel_id: int) -> None:
        super().__init__()
        self.on_back = on_back
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            parse_duration(str(self.duracao.value))
        except InvalidDurationError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        raw_winners = str(self.vencedores.value).strip()
        if not raw_winners.isdigit() or int(raw_winners) < 1:
            await interaction.response.send_message(
                "Quantidade de vencedores precisa ser um número inteiro maior que zero.", ephemeral=True
            )
            return

        draft = _GiveawayDraft(
            on_back=self.on_back,
            channel_id=self.channel_id,
            title=str(self.titulo.value).strip(),
            description=str(self.descricao.value).strip() or None,
            duration_text=str(self.duracao.value).strip(),
            winners_count=int(raw_winners),
        )
        await interaction.response.edit_message(
            content="**Passo 3/4** — Restrinja por cargo (opcional, vazio = todo mundo):",
            embed=None,
            view=_RolesPickView(draft),
        )


class _RolesPickView(SafeView):
    def __init__(self, draft: _GiveawayDraft) -> None:
        super().__init__(timeout=300)
        self.draft = draft
        self.add_item(_RolesPicker(draft))
        self.add_item(_BackButton(lambda i: _back_to_giveaway_menu(draft.on_back, i)))


class _RolesPicker(discord.ui.RoleSelect):
    def __init__(self, draft: _GiveawayDraft) -> None:
        super().__init__(
            placeholder="Cargos permitidos (vazio = todo mundo)", min_values=0, max_values=25
        )
        self.draft = draft

    async def callback(self, interaction: discord.Interaction) -> None:
        self.draft.allowed_role_ids = [role.id for role in self.values]
        await interaction.response.edit_message(
            content="**Passo 4/4** — Escolha o tipo de prêmio:",
            embed=None,
            view=_PrizeTypeView(self.draft),
        )


class _PrizeTypeView(SafeView):
    def __init__(self, draft: _GiveawayDraft) -> None:
        super().__init__(timeout=300)
        self.draft = draft
        self.add_item(_BackButton(lambda i: _back_to_giveaway_menu(draft.on_back, i), row=1))

    @discord.ui.button(label="🎭 Cargo", style=discord.ButtonStyle.primary)
    async def role_prize_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content="Escolha o cargo que o(s) vencedor(es) vão receber:",
            embed=None,
            view=_PrizeRolePickView(self.draft),
        )

    @discord.ui.button(label="📝 Personalizado", style=discord.ButtonStyle.secondary)
    async def custom_prize_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(_PrizeTextModal(self.draft))


class _PrizeRolePickView(SafeView):
    def __init__(self, draft: _GiveawayDraft) -> None:
        super().__init__(timeout=300)
        self.draft = draft
        self.add_item(_PrizeRolePicker(draft))
        self.add_item(_BackButton(lambda i: _back_to_giveaway_menu(draft.on_back, i)))


class _PrizeRolePicker(discord.ui.RoleSelect):
    def __init__(self, draft: _GiveawayDraft) -> None:
        super().__init__(placeholder="Cargo-prêmio", min_values=1, max_values=1)
        self.draft = draft

    async def callback(self, interaction: discord.Interaction) -> None:
        await _publish_giveaway(
            interaction,
            self.draft,
            prize_type=GiveawayPrizeType.ROLE,
            prize_role_id=self.values[0].id,
            prize_text=None,
        )


class _PrizeTextModal(discord.ui.Modal, title="Prêmio personalizado"):
    texto: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Prêmio (ex: 1 dia de vip)", max_length=500, required=True
    )

    def __init__(self, draft: _GiveawayDraft) -> None:
        super().__init__()
        self.draft = draft

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await _publish_giveaway(
            interaction,
            self.draft,
            prize_type=GiveawayPrizeType.CUSTOM,
            prize_role_id=None,
            prize_text=str(self.texto.value).strip(),
        )


async def _publish_giveaway(
    interaction: discord.Interaction,
    draft: _GiveawayDraft,
    *,
    prize_type: GiveawayPrizeType,
    prize_role_id: int | None,
    prize_text: str | None,
) -> None:
    from cogs.giveaways import GiveawayOpenView

    assert interaction.guild_id is not None
    bot: "LimerenceBot" = interaction.client  # type: ignore[assignment]

    guild = bot.get_guild(interaction.guild_id)
    channel = guild.get_channel(draft.channel_id) if guild else None
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ Canal configurado não existe mais ou não é um canal de texto.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)
    try:
        giveaway = await bot.giveaway_service.create_giveaway(
            guild_id=interaction.guild_id,
            creator_id=interaction.user.id,
            channel_id=draft.channel_id,
            title=draft.title,
            description=draft.description,
            duration=parse_duration(draft.duration_text),
            winners_count=draft.winners_count,
            allowed_role_ids=draft.allowed_role_ids,
            prize_type=prize_type,
            prize_role_id=prize_role_id,
            prize_text=prize_text,
        )
    except InvalidWinnersCountError as exc:
        await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        return

    message = await channel.send(embed=giveaway_panel_embed(giveaway, 0), view=GiveawayOpenView(giveaway.id))
    pin_warning = ""
    try:
        await message.pin(reason="Painel fixo de sorteio")
    except discord.HTTPException:
        pin_warning = " (sem permissão para fixar a mensagem)"
    await bot.giveaway_service.set_message_id(giveaway.id, message.id)

    await bot.audit_log_service.record(
        guild_id=interaction.guild_id,
        category=AuditLogCategory.GIVEAWAY,
        action="SORTEIO_CRIADO",
        executor_id=interaction.user.id,
        executor_name=str(interaction.user),
        details={"giveaway_id": str(giveaway.id), "title": giveaway.title},
    )

    await interaction.followup.send(
        f"✅ Sorteio criado e enviado em {channel.mention}!{pin_warning}", ephemeral=True
    )
