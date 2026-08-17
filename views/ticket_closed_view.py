from __future__ import annotations

import io
from typing import TYPE_CHECKING

import discord

from database.models.log import LogAction
from database.models.ticket import Ticket
from services.evaluation_service import normalize_evaluation_method
from services.ticket_service import TicketNotFoundError
from utils.checks import member_can, member_is_staff
from utils.ticket_lifecycle import schedule_channel_deletion
from utils.transcript import build_transcript_html, build_transcript_pdf, save_transcript_locally
from views.base_view import SafeView
from views.dm_evaluation_view import DMEvaluationView

if TYPE_CHECKING:
    from core.bot import LimerenceBot


async def _deny_if_not_staff(interaction: discord.Interaction) -> bool:
    # Os 3 botoes desta view sempre deferem antes de chamar isto (nenhum
    # deles abre modal), entao a recusa sai por followup.
    if await member_is_staff(interaction):
        return False
    await interaction.followup.send(
        "Apenas a staff pode usar esses botões.", ephemeral=True
    )
    return True


async def _deny_if_cant(interaction: discord.Interaction, action: str) -> bool:
    if await member_can(interaction, action):
        return False
    await interaction.followup.send(
        "Você não tem permissão para usar esse botão.", ephemeral=True
    )
    return True


async def send_ticket_transcript(interaction: discord.Interaction) -> None:
    """Gera e envia a transcricao (HTML+PDF) do canal atual. Compartilhado
    entre o botao Transcrição (pos-fechamento, `TicketClosedView`) e a opcao
    'Gerar transcrição' do menu ⚙️ Mais (ticket ainda aberto) — mesma logica,
    sem duplicar. Quem chama ja deve ter deferido a interaction (ephemeral,
    thinking=True) e checado que quem clicou e staff."""
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel) or interaction.channel_id is None:
        return

    ticket = await bot.ticket_service.get_by_channel_id(interaction.channel_id)
    if ticket is None:
        await interaction.followup.send("Ticket não encontrado.", ephemeral=True)
        return

    behaviour = await bot.ticket_panel_service.behaviour_for_ticket(ticket, ticket.guild_id)
    if not behaviour.transcript_enabled:
        await interaction.followup.send(
            "A transcrição está desativada no painel que originou este ticket.",
            ephemeral=True,
        )
        return

    html_content = await build_transcript_html(channel, ticket)
    pdf_content = await build_transcript_pdf(channel, ticket)
    save_transcript_locally(ticket, html_content, pdf_content)
    html_filename = f"transcricao-{str(ticket.id)[:8]}.html"
    pdf_filename = f"transcricao-{str(ticket.id)[:8]}.pdf"

    def _files() -> list[discord.File]:
        return [
            discord.File(io.BytesIO(html_content.encode()), filename=html_filename),
            discord.File(io.BytesIO(pdf_content), filename=pdf_filename),
        ]

    await channel.send(files=_files())

    settings = await bot.config_service.get_settings(ticket.guild_id)
    destination_channel_id = settings.transcript_channel_id or settings.log_channel_id
    if destination_channel_id is not None:
        destination = bot.get_channel(destination_channel_id)
        if isinstance(destination, discord.TextChannel):
            claimed_staff = (
                await bot.staff_service.get_by_id(ticket.claimed_by_staff_id)
                if ticket.claimed_by_staff_id is not None
                else None
            )
            embed = discord.Embed(
                title=f"📄 Transcrição — ticket #{str(ticket.id)[:8]}",
                description=(
                    f"**Canal:** {channel.name}\n"
                    f"**Aberto por:** <@{ticket.opened_by_discord_id}> "
                    f"(ID: `{ticket.opened_by_discord_id}`)\n"
                    f"**Assumido por:** {claimed_staff.display_name if claimed_staff else 'Ninguém assumiu'}\n"
                    f"**Gerado por:** {interaction.user.mention}"
                ),
            )
            await destination.send(embed=embed, files=_files())

    await interaction.followup.send("Transcrição gerada.", ephemeral=True)


class TicketClosedView(SafeView):
    """Botoes Transcricao/Reabrir/Excluir, mostrados apos o fechamento
    confirmado. Persistent (timeout=None), resolve o ticket pelo channel_id."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Transcrição",
        style=discord.ButtonStyle.primary,
        custom_id="limerence:ticket:transcript",
        emoji="📄",
    )
    async def transcript(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        # Deferir de imediato: nao ha ramo de modal aqui, e as checagens
        # (staff, ticket, comportamento do painel) + geracao da transcricao
        # sao varias idas ao banco/HTTP que facilmente passam dos 3s.
        await interaction.response.defer(ephemeral=True, thinking=True)
        if await _deny_if_not_staff(interaction):
            return
        await send_ticket_transcript(interaction)

    @discord.ui.button(
        label="Reabrir",
        style=discord.ButtonStyle.success,
        custom_id="limerence:ticket:reopen",
        emoji="🔓",
    )
    async def reopen(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        # Deferir de imediato: sem ramo de modal, e reopen_ticket ja e uma
        # escrita no banco antes de qualquer resposta.
        await interaction.response.defer()
        if await _deny_if_cant(interaction, "reabrir"):
            return
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        guild = interaction.guild
        member = interaction.user
        channel = interaction.channel
        if guild is None or interaction.channel_id is None or not isinstance(channel, discord.TextChannel):
            return

        from views.ticket_actions_view import TicketActionsView

        try:
            ticket = await bot.ticket_service.reopen_ticket(interaction.channel_id)
        except TicketNotFoundError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.edit_original_response(view=self)

        await channel.send(
            content=f"🔓 Ticket reaberto por {member.mention}.", view=TicketActionsView(ticket)
        )

        await bot.log_service.record(
            guild_id=guild.id,
            action=LogAction.REABERTURA,
            actor_discord_id=member.id,
            ticket_id=ticket.id,
            category_snapshot=ticket.category.value,
            message=f"{member} reabriu o ticket.",
        )
        await bot.painel_service.refresh_dashboard(guild.id)

    @discord.ui.button(
        label="Excluir",
        style=discord.ButtonStyle.danger,
        custom_id="limerence:ticket:delete",
        emoji="🗑️",
    )
    async def delete(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        # Deferir de imediato: sem ramo de modal, e a checagem de permissao +
        # get_by_channel_id ja rodam antes de qualquer resposta.
        await interaction.response.defer()
        if await _deny_if_cant(interaction, "excluir"):
            return
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        guild = interaction.guild
        member = interaction.user
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or interaction.channel_id is None:
            return

        ticket = await bot.ticket_service.get_by_channel_id(interaction.channel_id)

        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.edit_original_response(view=self)

        behaviour = (
            await bot.ticket_panel_service.behaviour_for_ticket(ticket, guild.id)
            if guild is not None
            else None
        )

        if (
            ticket is not None
            and ticket.claimed_by_staff_id is not None
            and (behaviour is None or behaviour.dm_on_close_enabled)
            and guild is not None
        ):
            eval_settings = await bot.config_service.get_evaluation_settings(guild.id)
            method = normalize_evaluation_method(eval_settings.evaluation_method)
            # "dm"/"both" ja mandou a DM de avaliacao no fechamento
            # (ticket_actions_view._send_evaluation_dm) — mandar de novo aqui
            # duplicaria. Fallback so faz sentido quando metodo era "ticket"
            # (nenhuma DM saiu antes) e o ticket foi excluido sem avaliacao.
            if method not in ("dm", "both"):
                evaluated = await bot.evaluation_service.has_evaluation(ticket.id)
                if not evaluated:
                    await self._dm_evaluation_fallback(bot, guild, ticket, channel)

        if guild is not None:
            await bot.log_service.record(
                guild_id=guild.id,
                action=LogAction.EXCLUSAO,
                actor_discord_id=member.id,
                ticket_id=ticket.id if ticket is not None else None,
                category_snapshot=ticket.category.value if ticket is not None else None,
                message=f"{member} excluiu o ticket.",
            )

        if behaviour is not None:
            schedule_channel_deletion(
                channel, f"excluído por {member}", behaviour.delete_delay_seconds
            )
        else:
            schedule_channel_deletion(channel, f"excluído por {member}")

    @staticmethod
    async def _dm_evaluation_fallback(
        bot: LimerenceBot, guild: discord.Guild | None, ticket: Ticket, channel: discord.TextChannel
    ) -> None:
        opener = bot.get_user(ticket.opened_by_discord_id)
        if opener is None:
            try:
                opener = await bot.fetch_user(ticket.opened_by_discord_id)
            except discord.HTTPException:
                return

        try:
            await opener.send(
                embed=discord.Embed(
                    title="Como foi o seu atendimento?",
                    description=(
                        f"Seu ticket em **{guild.name if guild else 'nosso servidor'}** foi encerrado "
                        "antes de você avaliar o atendimento. Ainda dá tempo — avalie abaixo:"
                    ),
                ),
                view=DMEvaluationView(ticket.id),
            )
        except discord.HTTPException:
            # DM fechada ou bloqueou o bot — sem fallback possivel, so segue com a exclusao
            pass
