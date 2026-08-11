from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.ticket import Ticket, TicketApprovalStatus, TicketCategory
from database.models.ticket_form_response import TicketFormResponse
from database.models.ticket_panel import TicketPanel
from database.models.ticket_panel_form_field import MAX_FORM_FIELDS, TicketPanelFormField
from database.models.ticket_panel_group import MAX_GROUP_PANELS, TicketPanelGroup
from database.repositories.ticket_panel_repository import (
    TicketFormResponseRepository,
    TicketPanelFormFieldRepository,
    TicketPanelGroupRepository,
    TicketPanelRepository,
)
from database.repositories.ticket_repository import TicketRepository

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_BUTTON_STYLES: dict[str, discord.ButtonStyle] = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}

BUTTON_STYLE_LABELS: dict[str, str] = {
    "primary": "Azul (primary)",
    "secondary": "Cinza (secondary)",
    "success": "Verde (success)",
    "danger": "Vermelho (danger)",
}

SYSTEM_DISABLED_MESSAGE = (
    "🚫 O sistema de tickets está temporariamente desativado. Tente novamente mais tarde."
)
PANEL_DISABLED_MESSAGE = "🚫 Este painel de tickets está desativado no momento."


def button_style_from_value(value: str | None) -> discord.ButtonStyle:
    return _BUTTON_STYLES.get(value or "primary", discord.ButtonStyle.primary)


def member_matches_panel_claim_roles(
    member: discord.Member, panel: TicketPanel | None
) -> bool:
    """Filtro EXTRA de quem pode atuar nos tickets de um painel.

    Escolha de design (opcao "a" do plano): a permissao global de `claim`
    (permission_settings + utils.checks.member_can) continua sendo a fonte da
    verdade; `panel.claim_role_ids` so restringe ainda mais, por painel. Lista
    vazia = sem restricao extra. Nao existe sistema de permissao paralelo."""
    if panel is None or not panel.claim_role_ids:
        return True
    if member.guild_permissions.administrator:
        return True
    return bool({role.id for role in member.roles} & set(panel.claim_role_ids))


def slugify(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    return slug[:48] or "painel"


@dataclass(frozen=True)
class TicketBehaviour:
    """Flags de comportamento ja resolvidos pra um ticket (painel > guild)."""

    delete_delay_seconds: int
    auto_close_enabled: bool
    transcript_enabled: bool
    evaluation_enabled: bool
    dm_on_close_enabled: bool


class TicketPanelError(ValueError):
    """Erro de regra de negocio dos paineis de ticket (mensagem mostrada ao admin)."""


class TicketPanelService:
    """Regras dos paineis de ticket configuraveis. Cada painel e uma linha em
    `ticket_panels` — nome, embed, botao, comportamento, formulario e aprovacao
    sao 100% definidos pelo admin no /config, nada e fixo no codigo.

    Este servico NAO reimplementa ticket: a criacao do canal, o claim/fechar/
    reabrir, transcricao e estatisticas continuam sendo do TicketService +
    TicketActionsView. Aqui so mora o que e especifico de painel."""

    def __init__(self, database: Database, bot: LimerenceBot) -> None:
        self._database = database
        self._bot = bot

    # --- CRUD de paineis ---------------------------------------------------

    async def list_panels(self, guild_id: int, *, only_enabled: bool = False) -> list[TicketPanel]:
        async with self._database.session() as session:
            return await TicketPanelRepository(session).list_by_guild(
                guild_id, only_enabled=only_enabled
            )

    async def get_panel(self, panel_id: uuid.UUID) -> TicketPanel | None:
        async with self._database.session() as session:
            return await TicketPanelRepository(session).get_by_id(panel_id)

    async def get_panel_by_key(self, guild_id: int, key: str) -> TicketPanel | None:
        async with self._database.session() as session:
            return await TicketPanelRepository(session).get_by_key(guild_id, key)

    async def create_panel(self, guild_id: int, name: str) -> TicketPanel:
        name = name.strip()
        if not name:
            raise TicketPanelError("Dê um nome pro painel.")
        async with self._database.session() as session:
            repo = TicketPanelRepository(session)
            existing = await repo.list_by_guild(guild_id)
            if any(p.name.lower() == name.lower() for p in existing):
                raise TicketPanelError(f"Já existe um painel chamado '{name}' neste servidor.")
            taken = {p.key for p in existing}
            base = slugify(name)
            key = base
            suffix = 2
            while key in taken:
                key = f"{base}-{suffix}"
                suffix += 1
            return await repo.add(
                TicketPanel(
                    guild_id=guild_id,
                    key=key,
                    name=name,
                    button_label=f"Abrir {name}"[:80],
                )
            )

    async def update_panel(self, panel_id: uuid.UUID, **fields: object) -> TicketPanel:
        async with self._database.session() as session:
            repo = TicketPanelRepository(session)
            panel = await repo.get_by_id(panel_id)
            if panel is None:
                raise TicketPanelError("Painel não encontrado.")
            for key, value in fields.items():
                setattr(panel, key, value)
            await session.flush()
            await session.refresh(panel)
            return panel

    async def delete_panel(self, panel_id: uuid.UUID) -> None:
        panel = await self.get_panel(panel_id)
        if panel is None:
            return
        await self._delete_published_message(panel)
        async with self._database.session() as session:
            repo = TicketPanelRepository(session)
            row = await repo.get_by_id(panel_id)
            if row is not None:
                await repo.delete(row)

    # --- publicacao no Discord ---------------------------------------------

    def build_view(self, panel: TicketPanel) -> discord.ui.View:
        from views.ticket_panel_open_view import TicketPanelOpenView

        return TicketPanelOpenView(panel)

    def build_embed(self, panel: TicketPanel) -> discord.Embed:
        from views.embeds import open_ticket_panel_embed

        return open_ticket_panel_embed(panel)

    async def publish_panel(
        self, panel_id: uuid.UUID, channel: discord.TextChannel
    ) -> TicketPanel:
        panel = await self.get_panel(panel_id)
        if panel is None:
            raise TicketPanelError("Painel não encontrado.")
        await self._delete_published_message(panel)
        try:
            message = await channel.send(embed=self.build_embed(panel), view=self.build_view(panel))
        except discord.HTTPException as exc:
            raise TicketPanelError(
                "Não foi possível publicar o painel nesse canal — confira as permissões do bot."
            ) from exc
        self._bot.add_view(self.build_view(panel), message_id=message.id)
        return await self.update_panel(panel_id, channel_id=channel.id, message_id=message.id)

    async def refresh_panel(self, panel_id: uuid.UUID) -> TicketPanel | None:
        """Reedita a mensagem ja publicada com a config atual. Se a mensagem
        sumiu (apagada na mão), limpa channel_id/message_id em vez de estourar."""
        panel = await self.get_panel(panel_id)
        if panel is None or panel.channel_id is None or panel.message_id is None:
            return panel
        channel = self._bot.get_channel(panel.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return await self.update_panel(panel_id, channel_id=None, message_id=None)
        try:
            message = await channel.fetch_message(panel.message_id)
            await message.edit(embed=self.build_embed(panel), view=self.build_view(panel))
        except discord.NotFound:
            return await self.update_panel(panel_id, channel_id=None, message_id=None)
        except discord.HTTPException:
            return panel
        return panel

    async def unpublish_panel(self, panel_id: uuid.UUID) -> TicketPanel:
        panel = await self.get_panel(panel_id)
        if panel is None:
            raise TicketPanelError("Painel não encontrado.")
        await self._delete_published_message(panel)
        return await self.update_panel(panel_id, channel_id=None, message_id=None)

    async def _delete_published_message(self, panel: TicketPanel) -> None:
        if panel.channel_id is None or panel.message_id is None:
            return
        channel = self._bot.get_channel(panel.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(panel.message_id)
            await message.delete()
        except discord.HTTPException:
            pass

    async def register_published_views(self) -> int:
        """Re-registra no boot uma view persistente por painel publicado, senão
        os botões param de responder depois de um restart."""
        async with self._database.session() as session:
            panels = await TicketPanelRepository(session).list_published()
        for panel in panels:
            self._bot.add_view(self.build_view(panel), message_id=panel.message_id)
        return len(panels)

    # --- combos (varios paineis, uma mensagem so) ---------------------------

    async def list_groups(self, guild_id: int) -> list[TicketPanelGroup]:
        async with self._database.session() as session:
            return await TicketPanelGroupRepository(session).list_by_guild(guild_id)

    async def get_group(self, group_id: uuid.UUID) -> TicketPanelGroup | None:
        async with self._database.session() as session:
            return await TicketPanelGroupRepository(session).get_by_id(group_id)

    async def get_group_panels(self, group: TicketPanelGroup) -> list[TicketPanel]:
        """Paineis do combo, na ordem salva (panel_ids[0] = principal). Paineis
        excluidos depois de entrarem no combo sao silenciosamente pulados —
        o botao deles so some, o resto do combo continua funcionando."""
        panels: list[TicketPanel] = []
        for raw_id in group.panel_ids:
            panel = await self.get_panel(uuid.UUID(raw_id))
            if panel is not None and panel.guild_id == group.guild_id:
                panels.append(panel)
        return panels

    async def create_group(
        self, guild_id: int, name: str, panel_ids: list[uuid.UUID]
    ) -> TicketPanelGroup:
        name = name.strip()
        if not name:
            raise TicketPanelError("Dê um nome pro combo.")
        if len(panel_ids) < 2:
            raise TicketPanelError("Escolha pelo menos 2 painéis pro combo.")
        if len(panel_ids) > MAX_GROUP_PANELS:
            raise TicketPanelError(f"Um combo aceita no máximo {MAX_GROUP_PANELS} painéis.")
        async with self._database.session() as session:
            panel_repo = TicketPanelRepository(session)
            for panel_id in panel_ids:
                panel = await panel_repo.get_by_id(panel_id)
                if panel is None or panel.guild_id != guild_id:
                    raise TicketPanelError("Um dos painéis escolhidos não foi encontrado.")
            return await TicketPanelGroupRepository(session).add(
                TicketPanelGroup(
                    guild_id=guild_id,
                    name=name,
                    panel_ids=[str(panel_id) for panel_id in panel_ids],
                )
            )

    async def update_group(self, group_id: uuid.UUID, **fields: object) -> TicketPanelGroup:
        async with self._database.session() as session:
            repo = TicketPanelGroupRepository(session)
            group = await repo.get_by_id(group_id)
            if group is None:
                raise TicketPanelError("Combo não encontrado.")
            for key, value in fields.items():
                setattr(group, key, value)
            await session.flush()
            await session.refresh(group)
            return group

    async def delete_group(self, group_id: uuid.UUID) -> None:
        group = await self.get_group(group_id)
        if group is None:
            return
        await self._delete_published_group_message(group)
        async with self._database.session() as session:
            repo = TicketPanelGroupRepository(session)
            row = await repo.get_by_id(group_id)
            if row is not None:
                await repo.delete(row)

    def build_group_view(self, panels: list[TicketPanel]) -> discord.ui.View:
        from views.ticket_panel_open_view import TicketPanelGroupOpenView

        return TicketPanelGroupOpenView(panels)

    async def publish_group(
        self, group_id: uuid.UUID, channel: discord.TextChannel
    ) -> TicketPanelGroup:
        group = await self.get_group(group_id)
        if group is None:
            raise TicketPanelError("Combo não encontrado.")
        panels = await self.get_group_panels(group)
        if len(panels) < 2:
            raise TicketPanelError(
                "Este combo ficou com menos de 2 painéis válidos — edite os painéis antes de publicar."
            )
        await self._delete_published_group_message(group)
        try:
            message = await channel.send(
                embed=self.build_embed(panels[0]), view=self.build_group_view(panels)
            )
        except discord.HTTPException as exc:
            raise TicketPanelError(
                "Não foi possível publicar o combo nesse canal — confira as permissões do bot."
            ) from exc
        self._bot.add_view(self.build_group_view(panels), message_id=message.id)
        return await self.update_group(group_id, channel_id=channel.id, message_id=message.id)

    async def refresh_group(self, group_id: uuid.UUID) -> TicketPanelGroup | None:
        group = await self.get_group(group_id)
        if group is None or group.channel_id is None or group.message_id is None:
            return group
        channel = self._bot.get_channel(group.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return await self.update_group(group_id, channel_id=None, message_id=None)
        panels = await self.get_group_panels(group)
        if len(panels) < 2:
            return group
        try:
            message = await channel.fetch_message(group.message_id)
            await message.edit(embed=self.build_embed(panels[0]), view=self.build_group_view(panels))
        except discord.NotFound:
            return await self.update_group(group_id, channel_id=None, message_id=None)
        except discord.HTTPException:
            return group
        return group

    async def unpublish_group(self, group_id: uuid.UUID) -> TicketPanelGroup:
        group = await self.get_group(group_id)
        if group is None:
            raise TicketPanelError("Combo não encontrado.")
        await self._delete_published_group_message(group)
        return await self.update_group(group_id, channel_id=None, message_id=None)

    async def _delete_published_group_message(self, group: TicketPanelGroup) -> None:
        if group.channel_id is None or group.message_id is None:
            return
        channel = self._bot.get_channel(group.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(group.message_id)
            await message.delete()
        except discord.HTTPException:
            pass

    async def register_published_groups(self) -> int:
        """Re-registra no boot uma view persistente por combo publicado, senão
        os botões param de responder depois de um restart."""
        async with self._database.session() as session:
            groups = await TicketPanelGroupRepository(session).list_published()
        count = 0
        for group in groups:
            panels = await self.get_group_panels(group)
            if len(panels) < 2:
                continue
            self._bot.add_view(self.build_group_view(panels), message_id=group.message_id)
            count += 1
        return count

    # --- formulario ---------------------------------------------------------

    async def list_form_fields(self, panel_id: uuid.UUID) -> list[TicketPanelFormField]:
        async with self._database.session() as session:
            return await TicketPanelFormFieldRepository(session).list_by_panel(panel_id)

    async def add_form_field(
        self,
        panel_id: uuid.UUID,
        *,
        label: str,
        style: str = "short",
        required: bool = True,
        placeholder: str | None = None,
    ) -> TicketPanelFormField:
        async with self._database.session() as session:
            repo = TicketPanelFormFieldRepository(session)
            existing = await repo.list_by_panel(panel_id)
            if len(existing) >= MAX_FORM_FIELDS:
                raise TicketPanelError(
                    f"O formulário já tem {MAX_FORM_FIELDS} perguntas — esse é o limite de um "
                    "modal do Discord. Remova uma pergunta antes de adicionar outra."
                )
            return await repo.add(
                TicketPanelFormField(
                    panel_id=panel_id,
                    position=len(existing),
                    label=label.strip()[:45],
                    style=style if style in ("short", "long") else "short",
                    required=required,
                    placeholder=(placeholder or "").strip()[:100] or None,
                )
            )

    async def update_form_field(
        self, field_id: uuid.UUID, **fields: object
    ) -> TicketPanelFormField:
        async with self._database.session() as session:
            repo = TicketPanelFormFieldRepository(session)
            field = await repo.get_by_id(field_id)
            if field is None:
                raise TicketPanelError("Pergunta não encontrada.")
            for key, value in fields.items():
                setattr(field, key, value)
            await session.flush()
            await session.refresh(field)
            return field

    async def delete_form_field(self, field_id: uuid.UUID) -> None:
        async with self._database.session() as session:
            repo = TicketPanelFormFieldRepository(session)
            field = await repo.get_by_id(field_id)
            if field is None:
                return
            panel_id = field.panel_id
            await repo.delete(field)
            for position, remaining in enumerate(await repo.list_by_panel(panel_id)):
                remaining.position = position

    async def list_form_responses(self, ticket_id: uuid.UUID) -> list[TicketFormResponse]:
        async with self._database.session() as session:
            return await TicketFormResponseRepository(session).list_by_ticket(ticket_id)

    async def save_form_responses(
        self, ticket_id: uuid.UUID, answers: list[tuple[str, str]]
    ) -> None:
        async with self._database.session() as session:
            repo = TicketFormResponseRepository(session)
            for position, (label, answer) in enumerate(answers):
                await repo.add(
                    TicketFormResponse(
                        ticket_id=ticket_id,
                        position=position,
                        field_label=label[:45],
                        answer_text=answer,
                    )
                )

    # --- abertura de ticket a partir de um painel ---------------------------

    async def check_can_open(
        self, guild_id: int, member_id: int, panel: TicketPanel
    ) -> str | None:
        """Devolve a mensagem de bloqueio, ou None se pode abrir. Ordem: kill
        switch global (ticket_settings.enabled) -> painel -> limites."""
        ticket_settings = await self._bot.config_service.get_ticket_settings(guild_id)
        if not ticket_settings.enabled:
            return SYSTEM_DISABLED_MESSAGE
        if not panel.enabled:
            return PANEL_DISABLED_MESSAGE

        open_count = await self._bot.ticket_service.count_open_by_member(guild_id, member_id)
        if not panel.allow_multiple_tickets and open_count >= 1:
            return "Você já tem um ticket aberto. Feche-o antes de abrir outro."
        limit = (
            panel.max_tickets_per_user
            if panel.max_tickets_per_user is not None
            else ticket_settings.max_tickets_per_user
        )
        if limit is not None and open_count >= limit:
            return f"Você atingiu o limite de {limit} tickets abertos."
        return None

    def _resolve_role_ids(self, panel: TicketPanel, guild_settings: object) -> list[int]:
        """Cargos com acesso ao canal do ticket: os do painel; se o painel não
        configurou nenhum, cai nos cargos de staff globais da guild."""
        if panel.responsible_role_ids:
            return list(panel.responsible_role_ids)
        return [
            role_id
            for role_id in (
                getattr(guild_settings, "moderator_role_id", None),
                getattr(guild_settings, "dev_role_id", None),
                getattr(guild_settings, "ceo_role_id", None),
            )
            if role_id is not None
        ]

    async def open_ticket(
        self,
        interaction: discord.Interaction,
        panel: TicketPanel,
        *,
        answers: list[tuple[str, str]] | None = None,
    ) -> None:
        """Orquestra a abertura de um ticket vindo de um painel. Assume que a
        interaction JÁ foi respondida/deferida (efêmera) por quem chamou.

        Sequência dentro do canal criado:
          1. menção do autor + embed do ticket + TicketActionsView (assumir/fechar)
          2. embed com as respostas do formulário, se houver
          3. embed + botões Aprovar/Reprovar, se o painel exigir aprovação
        Ou seja, aprovação é uma mensagem A MAIS, não substitui os botões
        normais — o ticket segue sendo um ticket comum pra staff."""
        from views.embeds import (
            ticket_approval_request_embed,
            ticket_embed,
            ticket_form_answers_embed,
        )
        from views.ticket_actions_view import TicketActionsView
        from views.ticket_approval_view import TicketApprovalView

        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            await interaction.followup.send(
                "Este painel só funciona dentro de um servidor.", ephemeral=True
            )
            return

        blocked = await self.check_can_open(guild.id, member.id, panel)
        if blocked is not None:
            await interaction.followup.send(blocked, ephemeral=True)
            return

        guild_settings = await self._bot.config_service.get_settings(guild.id)
        role_ids = self._resolve_role_ids(panel, guild_settings)

        category_channel = None
        category_id = panel.ticket_category_id or guild_settings.ticket_category_id
        if category_id is not None:
            channel = guild.get_channel(category_id)
            if isinstance(channel, discord.CategoryChannel):
                category_channel = channel

        try:
            ticket, ticket_channel = await self._bot.ticket_service.create_ticket(
                guild,
                member,
                TicketCategory.OUTRO,
                category_channel,
                role_ids,
                panel=panel,
            )
        except discord.HTTPException:
            await interaction.followup.send(
                "Não foi possível criar o canal do ticket. Tente novamente mais tarde.",
                ephemeral=True,
            )
            return

        if answers:
            await self.save_form_responses(ticket.id, answers)

        await ticket_channel.send(
            content=member.mention, embed=ticket_embed(ticket, member), view=TicketActionsView()
        )
        if answers:
            await ticket_channel.send(embed=ticket_form_answers_embed(answers))
        if panel.approval_enabled:
            mentions = " ".join(f"<@&{role_id}>" for role_id in role_ids)
            await ticket_channel.send(
                content=mentions or None,
                embed=ticket_approval_request_embed(panel),
                view=TicketApprovalView(),
            )

        await interaction.followup.send(
            f"Seu ticket foi criado: {ticket_channel.mention}", ephemeral=True
        )
        await self._notify_alert_channel(guild, guild_settings, panel, member, ticket_channel, role_ids)
        await self._bot.audit_log_service.record(
            guild_id=guild.id,
            category=AuditLogCategory.TICKETS,
            action=f"Ticket aberto pelo painel '{panel.name}'",
            executor_id=member.id,
            executor_name=str(member),
            target_id=ticket_channel.id,
            target_name=ticket_channel.name,
            details={"painel": panel.name, "formulario": bool(answers)},
        )

    async def _notify_alert_channel(
        self,
        guild: discord.Guild,
        guild_settings: object,
        panel: TicketPanel,
        member: discord.Member,
        ticket_channel: discord.TextChannel,
        role_ids: list[int],
    ) -> None:
        from utils.constants import EMBED_COLOR_WARNING

        alert_channel_id = getattr(guild_settings, "ticket_alert_channel_id", None)
        if alert_channel_id is None:
            return
        alert_channel = guild.get_channel(alert_channel_id)
        if not isinstance(alert_channel, discord.TextChannel):
            return
        embed = discord.Embed(
            title="🔔 Novo ticket aberto",
            description=(
                f"Painel **{panel.name}** · aberto por {member.mention}\n"
                f"Canal: {ticket_channel.mention}"
            ),
            color=EMBED_COLOR_WARNING,
        )
        mentions = " ".join(f"<@&{role_id}>" for role_id in role_ids)
        await alert_channel.send(content=mentions or None, embed=embed)

    # --- comportamento efetivo de um ticket ---------------------------------

    async def behaviour_for_ticket(
        self, ticket: Ticket | None, guild_id: int
    ) -> TicketBehaviour:
        """Resolve os flags de comportamento que valem pra UM ticket: os do
        painel que o criou, ou os globais da guild quando o ticket veio do fluxo
        legado (panel_id NULL). Ponto unico de consulta pros consumidores
        (fechamento, transcricao, exclusao, inatividade)."""
        settings = await self._bot.config_service.get_ticket_settings(guild_id)
        panel = await self.get_panel_for_ticket(ticket) if ticket is not None else None
        if panel is None:
            return TicketBehaviour(
                delete_delay_seconds=settings.delete_delay_seconds,
                auto_close_enabled=settings.auto_close_enabled,
                transcript_enabled=True,
                evaluation_enabled=True,
                dm_on_close_enabled=True,
            )
        return TicketBehaviour(
            delete_delay_seconds=panel.delete_delay_seconds,
            auto_close_enabled=settings.auto_close_enabled and panel.auto_close_enabled,
            transcript_enabled=panel.transcript_enabled,
            evaluation_enabled=panel.evaluation_enabled,
            dm_on_close_enabled=panel.dm_on_close_enabled,
        )

    # --- aprovacao ----------------------------------------------------------

    async def get_panel_for_ticket(self, ticket: Ticket) -> TicketPanel | None:
        if ticket.panel_id is None:
            return None
        return await self.get_panel(ticket.panel_id)

    async def get_ticket_by_channel(self, channel_id: int) -> Ticket | None:
        async with self._database.session() as session:
            return await TicketRepository(session).get_by_channel_id(channel_id)

    async def review_ticket(
        self,
        interaction: discord.Interaction,
        *,
        approved: bool,
        reason: str | None = None,
    ) -> str:
        """Aprova/reprova o ticket do canal atual. Devolve a mensagem de
        resultado pra quem chamou mostrar. Aprovar entrega o cargo configurado
        no painel; reprovar não mexe em cargo nenhum. Os dois registram no audit
        log e avisam o autor por DM (falha de DM é ignorada)."""
        guild = interaction.guild
        if guild is None or interaction.channel_id is None:
            raise TicketPanelError("Este botão só funciona dentro de um servidor.")

        ticket = await self.get_ticket_by_channel(interaction.channel_id)
        if ticket is None:
            raise TicketPanelError("Ticket não encontrado para este canal.")
        panel = await self.get_panel_for_ticket(ticket)
        if panel is None or not panel.approval_enabled:
            raise TicketPanelError("Este ticket não tem etapa de aprovação.")
        if ticket.approval_status in (
            TicketApprovalStatus.APPROVED,
            TicketApprovalStatus.REPROVED,
        ):
            raise TicketPanelError("Este ticket já foi analisado.")

        status = TicketApprovalStatus.APPROVED if approved else TicketApprovalStatus.REPROVED
        await self._bot.ticket_service.set_approval_decision(
            interaction.channel_id, status=status, reviewer_id=interaction.user.id
        )

        granted_role: discord.Role | None = None
        author = guild.get_member(ticket.opened_by_discord_id)
        if approved and panel.approval_granted_role_id is not None and author is not None:
            role = guild.get_role(panel.approval_granted_role_id)
            if role is not None:
                try:
                    await author.add_roles(role, reason=f"Aprovado no painel {panel.name}")
                    granted_role = role
                except discord.HTTPException:
                    granted_role = None

        await self._bot.audit_log_service.record(
            guild_id=guild.id,
            category=AuditLogCategory.TICKETS,
            action=f"Ticket {'aprovado' if approved else 'reprovado'} no painel '{panel.name}'",
            executor_id=interaction.user.id,
            executor_name=str(interaction.user),
            target_id=ticket.opened_by_discord_id,
            target_name=str(author) if author is not None else None,
            reason=reason,
            details={
                "painel": panel.name,
                "cargo_entregue": granted_role.name if granted_role is not None else "—",
            },
        )
        await self._send_decision_dm(author, guild, panel, approved, granted_role, reason)

        if approved:
            extra = f" e recebeu o cargo {granted_role.mention}" if granted_role else ""
            return f"✅ Ticket aprovado por {interaction.user.mention}{extra}."
        return f"❌ Ticket reprovado por {interaction.user.mention}."

    async def _send_decision_dm(
        self,
        author: discord.Member | None,
        guild: discord.Guild,
        panel: TicketPanel,
        approved: bool,
        granted_role: discord.Role | None,
        reason: str | None,
    ) -> None:
        if author is None:
            return
        from utils.constants import EMBED_COLOR_DANGER, EMBED_COLOR_SUCCESS

        if approved:
            description = f"Sua solicitação no painel **{panel.name}** foi **aprovada**."
            if granted_role is not None:
                description += f"\nVocê recebeu o cargo **{granted_role.name}**."
        else:
            description = f"Sua solicitação no painel **{panel.name}** foi **reprovada**."
        if reason:
            description += f"\n\n**Motivo:** {reason}"

        embed = discord.Embed(
            title="✅ Solicitação aprovada" if approved else "❌ Solicitação reprovada",
            description=description,
            color=EMBED_COLOR_SUCCESS if approved else EMBED_COLOR_DANGER,
        )
        embed.set_footer(text=guild.name)
        try:
            await author.send(embed=embed)
        except discord.HTTPException:
            pass
