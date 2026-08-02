from __future__ import annotations

import time
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class TTLCache(Generic[K, V]):
    """Cache em memoria com expiracao por tempo, sem Redis — pensado pra
    valores por-guild que mudam raramente (ex.: mapa cargo->peso de voto) e
    que devem ser invalidados manualmente em toda escrita, nao so por TTL."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[K, tuple[float, V]] = {}

    def get(self, key: K) -> V | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            del self._entries[key]
            return None
        return value

    def set(self, key: K, value: V) -> None:
        self._entries[key] = (time.monotonic() + self._ttl, value)

    def invalidate(self, key: K) -> None:
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()
