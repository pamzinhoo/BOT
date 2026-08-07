from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from core.logger import get_logger

logger = get_logger("event_bus")

Handler = Callable[[Any], Awaitable[None]]


class EventBus:
    """Pub/sub interno em memoria (mesmo processo) — a ponte entre "backend
    muda estado" (LicenseService) e "bot reage" (RoleSyncService) descrita na
    Fase 5: quem publica um evento nao sabe nem se importa quem esta
    escutando. Um handler que falha nunca derruba o publisher nem os outros
    handlers — so loga e segue (mesmo principio de acoplamento opcional ja
    usado em SubscriptionService._notify_renewed)."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Handler]] = {}

    def subscribe(self, event_name: str, handler: Handler) -> None:
        self._subscribers.setdefault(event_name, []).append(handler)

    async def publish(self, event_name: str, payload: Any) -> None:
        for handler in self._subscribers.get(event_name, []):
            try:
                await handler(payload)
            except Exception:
                logger.exception(
                    "Handler de evento interno falhou (event=%s, handler=%s).",
                    event_name,
                    getattr(handler, "__qualname__", handler),
                )
