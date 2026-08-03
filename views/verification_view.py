from __future__ import annotations

import random
import re
import uuid
from contextlib import suppress
from typing import TYPE_CHECKING

import discord

from core.logger import get_logger
from database.models.verification_session import VerificationSession
from database.models.verification_settings import VerificationMethod
from services.verification_service import (
    DEFAULT_WELCOME_MESSAGE,
    VerificationOutcome,
    VerificationPrompt,
    render_placeholders,
)
from utils.constants import EMBED_COLOR_VIOLET
from views.base_view import SafeView
from views.embeds import verification_prompt_embed

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("verification_view")


def _build_prompt_view(session: VerificationSession) -> discord.ui.View:
    if session.method == VerificationMethod.BUTTON:
        return _build_button_view(session.id, session.generation, session.code, session.decoys)
    return _build_type_view(session.id)


def _build_type_view(session_id: uuid.UUID) -> discord.ui.View:
    view = SafeView(timeout=None)
    view.add_item(TypeCaptchaButton(session_id))
    return view


def _build_button_view(
    session_id: uuid.UUID, generation: int, code: str, decoys: list[str]
) -> discord.ui.View:
    candidates = [code, *decoys]
    random.shuffle(candidates)
    view = SafeView(timeout=None)
    for candidate in candidates:
        view.add_item(PickCaptchaButton(session_id, generation, candidate))
    return view


class VerificationPanelStartButton(discord.ui.Button):
    """Botao da mensagem fixa (pinada) em verification_channel_id. Cada clique
    inicia/reaproveita a sessao do membro e entrega o CAPTCHA numa mensagem
    efemera (so quem clicou ve) — resolve o caso de DM fechada sem depender
    de o membro abrir a DM do bot."""

    def __init__(self) -> None:
        super().__init__(
            style=discord.ButtonStyle.success,
            label="🔑 Iniciar Verificação",
            custom_id="limerence:verify:panel:start",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        member = interaction.user
        if interaction.guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Use este botão dentro do servidor.", ephemeral=True
            )
            return

        settings = await bot.verification_service.get_settings(interaction.guild.id)
        if settings.verified_role_id is not None:
            role = interaction.guild.get_role(settings.verified_role_id)
            if role is not None and role in member.roles:
                await interaction.response.send_message("Você já está verificado. ✅", ephemeral=True)
                return

        prompt = await bot.verification_service.start_verification(member)
        if prompt is None:
            await interaction.response.send_message(
                "Sistema de verificação está desativado no momento.", ephemeral=True
            )
            return

        welcome = settings.welcome_message or DEFAULT_WELCOME_MESSAGE
        text = render_placeholders(welcome, user=member.mention, server_name=interaction.guild.name)
        embed = verification_prompt_embed(text, code=prompt.code)
        view = _build_prompt_view(prompt.session)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        await bot.verification_service.set_delivery(
            prompt.session.id, via_dm=False, channel_id=interaction.channel_id, message_id=None
        )


class VerificationPanelView(SafeView):
    """View persistente da mensagem fixa — um unico botao estatico, registrada
    uma vez no boot (sem custom_id dinamico, igual PainelView/ShopPanelView)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(VerificationPanelStartButton())


def _is_panel_delivery(session: VerificationSession | None) -> bool:
    """Sessao entregue pelo botao do painel fixo: canal (nao DM) mas sem
    message_id salvo, porque a mensagem original e efemera (nao pode ser
    reaberta via fetch_message — so editada dentro da propria interaction)."""
    return session is not None and not session.via_dm and session.message_id is None


async def send_verification_prompt(
    bot: LimerenceBot, member: discord.Member, prompt: VerificationPrompt
) -> None:
    """Entrega a mensagem inicial de verificacao por DM; se a DM estiver fechada,
    cai pro canal de verificacao configurado da guild. Nunca bloqueia a
    verificacao so por causa da DM fechada — so registra se nao tiver nem DM
    nem canal de fallback configurado."""
    settings = await bot.verification_service.get_settings(member.guild.id)
    welcome = settings.welcome_message or DEFAULT_WELCOME_MESSAGE
    text = render_placeholders(welcome, user=member.mention, server_name=member.guild.name)
    embed = verification_prompt_embed(text, code=prompt.code)
    view = _build_prompt_view(prompt.session)

    message: discord.Message | None = None
    via_dm = True
    channel_id: int | None = None
    try:
        dm_channel = member.dm_channel or await member.create_dm()
        message = await dm_channel.send(embed=embed, view=view)
        channel_id = dm_channel.id
    except discord.HTTPException:
        via_dm = False
        if settings.verification_channel_id is not None:
            channel = member.guild.get_channel(settings.verification_channel_id)
            if isinstance(channel, discord.abc.Messageable):
                try:
                    message = await channel.send(content=member.mention, embed=embed, view=view)
                    channel_id = settings.verification_channel_id
                except discord.HTTPException:
                    pass
        if message is None:
            logger.warning(
                "Não foi possível entregar a verificação de %s na guild %s "
                "(DM fechada e sem canal de verificação configurado).",
                member.id, member.guild.id,
            )

    if message is not None and channel_id is not None:
        await bot.verification_service.set_delivery(
            prompt.session.id, via_dm=via_dm, channel_id=channel_id, message_id=message.id
        )


async def _resolve_prompt_message(
    bot: LimerenceBot, session: VerificationSession
) -> discord.Message | None:
    if session.delivery_channel_id is None or session.message_id is None:
        return None
    channel: discord.abc.Messageable | None = None
    if session.via_dm:
        user = bot.get_user(session.user_id) or await bot.fetch_user(session.user_id)
        channel = user.dm_channel or await user.create_dm()
    else:
        guild = bot.get_guild(session.guild_id)
        if guild is not None:
            candidate = guild.get_channel(session.delivery_channel_id)
            channel = candidate if isinstance(candidate, discord.abc.Messageable) else None
    if channel is None:
        return None
    try:
        return await channel.fetch_message(session.message_id)
    except discord.HTTPException:
        return None


def _final_embed(title: str, description: str) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=EMBED_COLOR_VIOLET)


async def _build_refresh(
    bot: LimerenceBot, outcome: VerificationOutcome, *, mention: str
) -> tuple[discord.Embed, discord.ui.View | None] | None:
    session = outcome.session
    if session is None:
        return None

    if outcome.status == "wrong":
        settings = await bot.verification_service.get_settings(session.guild_id)
        welcome = settings.welcome_message or DEFAULT_WELCOME_MESSAGE
        guild = bot.get_guild(session.guild_id)
        text = render_placeholders(welcome, user=mention, server_name=guild.name if guild else "o servidor")
        return verification_prompt_embed(text, code=session.code), _build_prompt_view(session)

    titles = {
        "success": "✅ Verificação concluída",
        "expired": "⌛ Verificação expirada",
        "max_attempts": "🚫 Verificação encerrada",
    }
    if outcome.status not in titles:
        return None
    return _final_embed(titles[outcome.status], outcome.message), None


async def _apply_outcome_to_persistent_message(
    bot: LimerenceBot, outcome: VerificationOutcome, *, mention: str
) -> None:
    """Atualiza a mensagem original de verificacao (DM ou canal de fallback)
    depois de uma tentativa. So mexe na mensagem quando o resultado muda o
    estado dela (codigo novo, sucesso, expiracao, tentativas esgotadas) —
    tentativas invalidas/stale/cooldown nao alteram nada."""
    if outcome.session is None:
        return
    refresh = await _build_refresh(bot, outcome, mention=mention)
    if refresh is None:
        return
    embed, view = refresh
    message = await _resolve_prompt_message(bot, outcome.session)
    if message is None:
        return
    with suppress(discord.HTTPException):
        await message.edit(embed=embed, view=view)


class TypeCaptchaModal(discord.ui.Modal, title="Verificação"):
    codigo = discord.ui.TextInput(
        label="Digite o código exibido",
        placeholder="Ex: X7P4KM",
        required=True,
        max_length=8,
    )

    def __init__(self, session_id: uuid.UUID) -> None:
        super().__init__()
        self.session_id = session_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        outcome = await bot.verification_service.submit_type_attempt(
            session_id=self.session_id,
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            submitted_code=str(self.codigo.value),
        )
        if _is_panel_delivery(outcome.session):
            # entrega efemera do painel fixo: so da pra editar a propria
            # mensagem da interaction, nunca reabrir via fetch_message.
            refresh = await _build_refresh(bot, outcome, mention=interaction.user.mention)
            if refresh is not None:
                embed, view = refresh
                await interaction.response.edit_message(content=outcome.message, embed=embed, view=view)
            else:
                await interaction.response.edit_message(content=outcome.message)
            return
        await interaction.response.send_message(outcome.message, ephemeral=True)
        await _apply_outcome_to_persistent_message(bot, outcome, mention=interaction.user.mention)


class TypeCaptchaButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"limerence:verify:type:(?P<session_id>[0-9a-fA-F-]{36})",
):
    """Botao persistente (DM ou canal de fallback) que abre o modal de digitar
    o codigo. Sobrevive a restart do bot (DynamicItem, sem timeout)."""

    def __init__(self, session_id: uuid.UUID) -> None:
        super().__init__(
            discord.ui.Button(
                label="🔑 Digitar código",
                style=discord.ButtonStyle.primary,
                custom_id=f"limerence:verify:type:{session_id}",
            )
        )
        self.session_id = session_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]
    ) -> TypeCaptchaButton:
        return cls(uuid.UUID(match["session_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(TypeCaptchaModal(self.session_id))


class PickCaptchaButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=(
        r"limerence:verify:pick:(?P<session_id>[0-9a-fA-F-]{36}):"
        r"(?P<generation>\d+):(?P<candidate>[A-Za-z0-9]{1,8})"
    ),
):
    """Botao persistente de um dos 4 candidatos (metodo 'Selecionar CAPTCHA').
    `generation` no custom_id trava esse botao a geracao do codigo em que foi
    criado — se o codigo for regenerado (erro anterior), botoes de geracoes
    antigas passam a ser rejeitados pelo VerificationService."""

    def __init__(self, session_id: uuid.UUID, generation: int, candidate: str) -> None:
        super().__init__(
            discord.ui.Button(
                label=candidate,
                style=discord.ButtonStyle.secondary,
                custom_id=f"limerence:verify:pick:{session_id}:{generation}:{candidate}",
            )
        )
        self.session_id = session_id
        self.generation = generation
        self.candidate = candidate

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]
    ) -> PickCaptchaButton:
        return cls(uuid.UUID(match["session_id"]), int(match["generation"]), match["candidate"])

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        outcome = await bot.verification_service.submit_button_attempt(
            session_id=self.session_id,
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            generation=self.generation,
            candidate=self.candidate,
        )
        if _is_panel_delivery(outcome.session):
            refresh = await _build_refresh(bot, outcome, mention=interaction.user.mention)
            if refresh is not None:
                embed, view = refresh
                await interaction.response.edit_message(content=outcome.message, embed=embed, view=view)
            else:
                await interaction.response.edit_message(content=outcome.message)
            return

        await interaction.response.send_message(outcome.message, ephemeral=True)

        refresh = await _build_refresh(bot, outcome, mention=interaction.user.mention)
        if refresh is not None and isinstance(interaction.message, discord.Message):
            embed, view = refresh
            with suppress(discord.HTTPException):
                await interaction.message.edit(embed=embed, view=view)
