from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from database.models.partnership_settings import PartnershipSettings
from services.partnership_service import PartnershipError

if TYPE_CHECKING:
    from core.bot import LimerenceBot


class PartnershipPublishModal(discord.ui.Modal, title="Publicar parceria"):
    """Campos montados dinamicamente conforme a configuração da guild (/config
    -> Parcerias): Convite e Banner só aparecem se estiverem permitidos, e o
    limite de caracteres da Descrição respeita `max_description_length`."""

    def __init__(self, settings: PartnershipSettings) -> None:
        super().__init__()

        self.nome = discord.ui.TextInput(label="Nome", max_length=100, required=True)
        self.descricao = discord.ui.TextInput(
            label="Descrição",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=min(max(settings.max_description_length, 1), 4000),
        )
        self.categoria = discord.ui.TextInput(label="Categoria", required=False, max_length=100)
        self.add_item(self.nome)
        self.add_item(self.descricao)
        self.add_item(self.categoria)

        self.convite: discord.ui.TextInput | None = None
        if settings.allow_invite:
            self.convite = discord.ui.TextInput(
                label="Convite do Discord", required=False, max_length=200
            )
            self.add_item(self.convite)

        self.banner: discord.ui.TextInput | None = None
        if settings.allow_banner:
            self.banner = discord.ui.TextInput(
                label="Banner (URL da imagem)", required=False, max_length=500
            )
            self.add_item(self.banner)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            record = await bot.partnership_service.publish(
                guild=guild,
                member=member,
                name=str(self.nome.value),
                description=str(self.descricao.value),
                invite=str(self.convite.value) if self.convite is not None else None,
                banner=str(self.banner.value) if self.banner is not None else None,
                category_label=str(self.categoria.value) if self.categoria.value else None,
            )
        except PartnershipError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

        location = f"<#{record.channel_id}>" if record.channel_id else f"<#{record.thread_id}>"
        await interaction.followup.send(f"✅ Parceria publicada em {location}.", ephemeral=True)
