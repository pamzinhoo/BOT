from __future__ import annotations

import time

_COMMAND_PREFIX = "!recorrer"


def parse_recorrer_dm_command(content: str) -> tuple[str, str] | None:
    """Parseia '!recorrer CODE motivo...' enviado por DM. Retorna (codigo, motivo)
    em maiusculas/trim, ou None se a mensagem nao bater com o formato esperado."""
    if not content.startswith(_COMMAND_PREFIX):
        return None
    rest = content[len(_COMMAND_PREFIX):].strip()
    parts = rest.split(maxsplit=1)
    if len(parts) != 2:
        return None
    code, motivo = parts
    motivo = motivo.strip()
    if not motivo:
        return None
    return code.strip().upper(), motivo


class DMAppealRateLimiter:
    """Limita tentativas de `!recorrer` por usuario numa janela deslizante — evita
    spam de recurso/consultas invalidas repetidas na DM (Etapa de seguranca)."""

    def __init__(self, max_attempts: int = 3, window_seconds: float = 60.0) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._attempts: dict[int, list[float]] = {}

    def allow(self, user_id: int, *, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        attempts = [t for t in self._attempts.get(user_id, []) if now - t < self._window_seconds]
        if len(attempts) >= self._max_attempts:
            self._attempts[user_id] = attempts
            return False
        attempts.append(now)
        self._attempts[user_id] = attempts
        return True
