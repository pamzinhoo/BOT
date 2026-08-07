from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Rate limit excedido, tente novamente em {retry_after_seconds:.1f}s")


class RateLimiter:
    """Janela deslizante em memoria, por chave arbitraria (ex.: IP, ou
    `ip+device_uuid`). In-process de proposito — a API roda embarcada no bot
    (`api/main.py`), uma unica instancia, sem Redis no stack atual. Nao
    escala pra multiplas instancias do processo; se isso mudar, trocar o
    dict interno por um backend compartilhado (Redis) mantendo a mesma
    interface `hit()`.
    """

    # A cada N chamadas de hit(), varre o dict inteiro removendo chaves cujo
    # bucket esvaziou. Sem isso, `_hits` cresce sem limite pela vida do
    # processo — toda chave unica que ja bateu aqui (IP, player_id,
    # device_uuid) fica no dict pra sempre, mesmo muito depois de parar de
    # ser usada. Pior em rotas publicas por IP (device_code/callback/webhook)
    # onde a cardinalidade de chaves e alta (memory leak em processo de
    # longa duracao). Intervalo escolhido pra manter o custo da varredura
    # amortizado (O(chaves ativas), nao O(1) por hit) sem deixar o dict
    # inchar demais entre varreduras.
    _SWEEP_EVERY_N_HITS = 256

    def __init__(self, *, max_hits: int, window_seconds: float) -> None:
        self._max_hits = max_hits
        self._window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._hits_since_sweep = 0

    async def hit(self, key: str) -> None:
        now = time.monotonic()
        async with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self._window_seconds:
                bucket.popleft()
            if len(bucket) >= self._max_hits:
                retry_after = self._window_seconds - (now - bucket[0])
                raise RateLimitExceeded(max(retry_after, 0.1))
            bucket.append(now)

            self._hits_since_sweep += 1
            if self._hits_since_sweep >= self._SWEEP_EVERY_N_HITS:
                self._hits_since_sweep = 0
                self._sweep_stale_locked(now)

    def _sweep_stale_locked(self, now: float) -> None:
        stale_keys = [
            key
            for key, bucket in self._hits.items()
            if not bucket or now - bucket[-1] > self._window_seconds
        ]
        for key in stale_keys:
            del self._hits[key]
