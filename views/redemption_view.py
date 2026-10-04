from __future__ import annotations

import asyncio
import re
import uuid

import discord

from core.logger import get_logger
from views.base_view import SafeView

logger = get_logger("redemption_view")

_CODE_PATTERN = re.compile(r"(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*[0-9])[A-Za-z0-9]{8}\Z")


class RedemptionModal(discord.ui.Modal, title="Resgatar código"):
    code = discord.ui.TextInput(
        label="Código de resgate",
        placeholder="8 letras e números",
        min_length=8,
        max_length=8,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if (
            interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
            or interaction.user.guild.id != interaction.guild.id
        ):
            await interaction.followup.send(
                "Resgate disponível somente no servidor.", ephemeral=True
            )
            return
        raw_code = str(self.code)
        if _CODE_PATTERN.fullmatch(raw_code) is None:
            await interaction.followup.send(
                "Código inválido. Use 8 caracteres, com letras e números.", ephemeral=True
            )
            return
        code = raw_code.upper()

        service = interaction.client.redemption_service  # type: ignore[attr-defined]
        try:
            result = await service.redeem(interaction.guild, interaction.user, code)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        if result["status"] != "delivered":
            await interaction.followup.send(
                result["message"], ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
            return

        redemption_id = uuid.UUID(result["id"])
        if not await service.claim_notification(interaction.guild.id, redemption_id):
            await interaction.followup.send(
                "Código já resgatado. A entrega privada já foi enviada ou está em processamento.",
                ephemeral=True,
            )
            return

        if result["delivery"] == "dm":
            try:
                async with asyncio.timeout(25):
                    await interaction.user.send(
                        result["message"], allowed_mentions=discord.AllowedMentions.none()
                    )
            except discord.Forbidden:
                try:
                    async with asyncio.timeout(25):
                        await interaction.followup.send(
                            result["message"],
                            ephemeral=True,
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                except (discord.HTTPException, TimeoutError):
                    await service.complete_notification(
                        interaction.guild.id, redemption_id, "uncertain"
                    )
                    raise
                await service.complete_notification(interaction.guild.id, redemption_id, "sent")
                return
            except (discord.HTTPException, TimeoutError):
                await service.complete_notification(
                    interaction.guild.id, redemption_id, "uncertain"
                )
                await interaction.followup.send(
                    "Resgate concluído, mas não foi possível confirmar a mensagem privada. "
                    "Verifique suas DMs antes de tentar novamente.",
                    ephemeral=True,
                )
                return
            await service.complete_notification(interaction.guild.id, redemption_id, "sent")
            await interaction.followup.send("Resgate concluído. Confira suas DMs.", ephemeral=True)
            return

        try:
            async with asyncio.timeout(25):
                await interaction.followup.send(
                    result["message"],
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except (discord.HTTPException, TimeoutError):
            await service.complete_notification(interaction.guild.id, redemption_id, "uncertain")
            raise
        await service.complete_notification(interaction.guild.id, redemption_id, "sent")

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.exception("Falha no resgate na guild %s.", interaction.guild_id, exc_info=error)
        message = "Não foi possível concluir o resgate agora. Tente novamente mais tarde."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass


class RedemptionButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="🎟️ Resgatar código",
            style=discord.ButtonStyle.primary,
            custom_id="limerence:shop:redeem",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(RedemptionModal())


def redemption_only_view() -> SafeView:
    view = SafeView(timeout=300)
    view.add_item(RedemptionButton())
    return view
