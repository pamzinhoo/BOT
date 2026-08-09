from __future__ import annotations

import pytest

from core.rate_limiter import RateLimiter, RateLimitExceeded


async def test_allows_hits_under_the_limit() -> None:
    limiter = RateLimiter(max_hits=3, window_seconds=60)
    await limiter.hit("k")
    await limiter.hit("k")
    await limiter.hit("k")  # nao levanta


async def test_blocks_hit_over_the_limit() -> None:
    limiter = RateLimiter(max_hits=2, window_seconds=60)
    await limiter.hit("k")
    await limiter.hit("k")
    with pytest.raises(RateLimitExceeded):
        await limiter.hit("k")


async def test_keys_are_independent() -> None:
    limiter = RateLimiter(max_hits=1, window_seconds=60)
    await limiter.hit("a")
    await limiter.hit("b")  # chave diferente, nao compartilha o balde


async def test_window_slides_and_frees_up_hits() -> None:
    limiter = RateLimiter(max_hits=1, window_seconds=0.05)
    await limiter.hit("k")
    with pytest.raises(RateLimitExceeded):
        await limiter.hit("k")

    import asyncio

    await asyncio.sleep(0.1)
    await limiter.hit("k")  # janela deslizou, libera de novo
