from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import discord

from utils.constants import EMBED_COLOR_SUCCESS, achievement_label

if TYPE_CHECKING:
    from core.bot import LimerenceBot


async def announce_achievements(
    bot: "LimerenceBot", channel: discord.abc.Messageable, staff_id: uuid.UUID, keys: list[str]
) -> None:
    if not keys:
        return
    staff = await bot.staff_service.get_by_id(staff_id)
    mention = f"<@{staff.discord_user_id}>" if staff else "Staff"
    lines = [achievement_label(key) for key in keys]
    await channel.send(
        embed=discord.Embed(
            title="🎉 Nova conquista desbloqueada!",
            description=f"{mention}\n" + "\n".join(lines),
            color=EMBED_COLOR_SUCCESS,
        )
    )
