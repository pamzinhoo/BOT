from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from api.routes.admin.security import require_local_admin

router = APIRouter(
    prefix="/admin/api",
    tags=["admin-events"],
    dependencies=[Depends(require_local_admin)],
)

_REFRESH_QUERIES = (
    "ready",
    "guilds",
    "overview",
    "settings",
    "discord-options",
    "panels",
    "tickets",
    "staff",
    "audit",
    "system",
    "giveaways",
    "dlcs",
)


def _event_payload(guild_id: int | None) -> str:
    payload = {
        "type": "dashboard.invalidate",
        "guild_id": str(guild_id) if guild_id is not None else None,
        "queries": list(_REFRESH_QUERIES),
        "source": "dashboard-events",
        "created_at": datetime.now(UTC).isoformat(),
    }
    return f"event: dashboard.invalidate\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def _event_stream(request: Request, guild_id: int | None) -> AsyncIterator[str]:
    yield _event_payload(guild_id)
    while not await request.is_disconnected():
        # Atualiza rapido o suficiente para tickets novos aparecerem sem o
        # usuario precisar trocar de aba, mas sem ficar batendo na API a cada
        # segundo. O painel e local, entao 5s e seguro e responsivo.
        await asyncio.sleep(5)
        yield _event_payload(guild_id)


@router.get("/events")
async def dashboard_events(request: Request, guild_id: int | None = Query(default=None)) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(request, guild_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
