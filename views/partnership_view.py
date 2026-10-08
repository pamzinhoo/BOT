from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from database.models.audit_log import AuditLogCategory
from services.social_notification_service import SocialNotificationValidationError
from views.base_view import SafeView
from views.embeds import partnership_how_it_works_embed

if TYPE_CHECKING:
    from core.bot import LimerenceBot


DEFAULT_PARTNER_ANNOUNCEMENT = "🎬 **VÍDEO NOVO!**\n\n" "Confira o novo conteúdo:\n" "{url}"


class PartnerAnnouncementModal(discord.ui.Modal, title="Publicar novo anúncio"):
    """Modal usado pelo parceiro para publicar um conteúdo no próprio canal."""

    url = discord.ui.TextInput(
        label="Link do conteúdo",
        placeholder="https://youtube.com/...",
        required=True,
        max_length=2048,
    )
    message = discord.ui.TextInput(
        label="Mensagem do anúncio",
        placeholder="Escreva sua mensagem. Use {url} onde o link deve aparecer.",
        style=discord.TextStyle.paragraph,
        default=DEFAULT_PARTNER_ANNOUNCEMENT,
        required=True,
        max_length=2000,
    )

    def __init__(
        self, bot: LimerenceBot, guild_id: int, creator_id: int, source_channel_id: int
    ) -> None:
        super().__init__()
        self._bot = bot
        self._guild_id = guild_id
        self._creator_id = creator_id
        self._source_channel_id = source_channel_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            partnership = await self._bot.partnership_service.get_partnership(
                self._guild_id, self._creator_id
            )
            if (
                partnership is None
                or partnership.channel_id != self._source_channel_id
                or partnership.archived_at is not None
            ):
                await interaction.followup.send(
                    "❌ Você não está autorizado a publicar anúncios por este canal.",
                    ephemeral=True,
                )
                return

            target_channel_id = self._source_channel_id

            notification = await self._bot.social_notification_service.send_manual(
                guild_id=self._guild_id,
                creator_id=self._creator_id,
                channel_id=target_channel_id,
                url=self.url.value,
                message_template=self.message.value,
                mention_everyone=True,
            )

            await self._bot.audit_log_service.record(
                guild_id=self._guild_id,
                category=AuditLogCategory.PARTNERSHIP,
                action="Anúncio de parceiro publicado",
                executor_id=self._creator_id,
                target_id=target_channel_id,
                details={
                    "social_notification_id": str(notification.id),
                    "source_channel_id": self._source_channel_id,
                    "message_id": notification.message_id,
                    "url": self.url.value,
                },
            )

            await interaction.followup.send(
                "✅ **Anúncio publicado com sucesso!**\n"
                "O conteúdo foi publicado neste canal com @everyone.",
                ephemeral=True,
            )
        except SocialNotificationValidationError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        except Exception:
            from core.logger import get_logger

            get_logger("partnership_view").exception(
                "Falha ao publicar anúncio do parceiro %s na guild %s.",
                self._creator_id,
                self._guild_id,
            )
            await interaction.followup.send(
                "❌ Não foi possível publicar o anúncio. Tente novamente ou avise a administração.",
                ephemeral=True,
            )


class PartnershipInfoView(SafeView):
    """Botões fixos na mensagem de boas-vindas do canal de parceiro.

    A view é persistente para continuar funcionando depois de reinícios do bot.
    A autorização do botão de anúncio é validada novamente no momento do clique.
    """

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Como funciona",
        emoji="📌",
        style=discord.ButtonStyle.secondary,
        custom_id="partnership:how_it_works",
    )
    async def how_it_works(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_message(
            embed=partnership_how_it_works_embed(), ephemeral=True
        )

    @discord.ui.button(
        label="Postar Anúncio",
        emoji="📢",
        style=discord.ButtonStyle.primary,
        custom_id="partnership:post_announcement",
    )
    async def post_announcement(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if interaction.guild is None or interaction.channel_id is None:
            await interaction.response.send_message(
                "❌ Esse botão só pode ser usado dentro do canal do parceiro.",
                ephemeral=True,
            )
            return

        bot = interaction.client
        if not hasattr(bot, "partnership_service") or not hasattr(
            bot, "social_notification_service"
        ):
            await interaction.response.send_message(
                "❌ Não foi possível acessar o sistema de parcerias.",
                ephemeral=True,
            )
            return

        partnership = await bot.partnership_service.get_partnership(
            interaction.guild.id, interaction.user.id
        )
        if (
            partnership is None
            or partnership.channel_id != interaction.channel_id
            or partnership.archived_at is not None
        ):
            await interaction.response.send_message(
                "❌ Apenas o parceiro responsável por este canal pode publicar anúncios.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            PartnerAnnouncementModal(
                bot=bot,
                guild_id=interaction.guild.id,
                creator_id=interaction.user.id,
                source_channel_id=interaction.channel_id,
            )
        )
