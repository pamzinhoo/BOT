from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from core.logger import get_logger

logger = get_logger("timing")


@asynccontextmanager
async def timed_step(operation: str, step: str) -> AsyncIterator[None]:
    """Instrumentacao leve e permanente pra fluxos criticos (claim/close/etc).

    So loga em DEBUG (`logger.isEnabledFor` evita ate formatar a mensagem
    quando o nivel esta acima disso — custo real em producao e proximo de
    zero). Usar em volta de uma etapa isolada (ex.: "db", "discord_api",
    "logging", "permission_check", "total") pra depois somar o tempo de cada
    fase de uma acao (claim/unclaim/fechar/criar ticket) sem instrumentar o
    codigo inteiro.

    Nao substitui profiling de verdade — e so um jeito barato de responder
    "qual etapa comeu o orcamento de 3s da interacao" quando o log estiver em
    DEBUG.
    """
    start = time.monotonic()
    try:
        yield
    finally:
        if logger.isEnabledFor(logging.DEBUG):
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.debug("perf op=%s step=%s duration_ms=%.1f", operation, step, elapsed_ms)
