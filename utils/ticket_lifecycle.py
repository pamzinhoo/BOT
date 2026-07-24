from __future__ import annotations

import asyncio

import discord

from utils.constants import TICKET_AUTO_DELETE_SECONDS


async def announce_and_delete_channel(
    channel: discord.TextChannel, announced_by: str, delay_seconds: int = TICKET_AUTO_DELETE_SECONDS
) -> None:
    """Avisa no canal que ele sera excluido em `delay_seconds` e apaga.

    Roda em background (fire-and-forget via asyncio.create_task) pra nao
    segurar a resposta da interacao que disparou a exclusao.
    """
    try:
        await channel.send(f"🗑️ Este ticket será excluído em {delay_seconds} segundos ({announced_by}).")
        await asyncio.sleep(delay_seconds)
        await channel.delete(reason=f"Ticket excluido — {announced_by}")
    except discord.NotFound:
        pass
    except discord.HTTPException:
        pass


def schedule_channel_deletion(
    channel: discord.TextChannel, announced_by: str, delay_seconds: int = TICKET_AUTO_DELETE_SECONDS
) -> None:
    asyncio.create_task(announce_and_delete_channel(channel, announced_by, delay_seconds))
