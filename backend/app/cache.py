"""Optional Redis + rate limiter (in-memory fallback)."""
from __future__ import annotations

import logging
import time

from app.config import settings

log = logging.getLogger(__name__)

_redis = None
_redis_checked_at = 0.0


async def get_redis():
    """Returns a connected redis client or None (graceful degradation)."""
    global _redis, _redis_checked_at
    if not settings.redis_url:
        return None
    if _redis is not None:
        return _redis
    if time.monotonic() - _redis_checked_at < 15:
        return None
    _redis_checked_at = time.monotonic()
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=2,
                                   decode_responses=True)
        await client.ping()
        _redis = client
    except Exception as e:  # noqa: BLE001
        log.warning("redis unavailable (%s); falling back to in-memory", e)
        _redis = None
    return _redis


class RateLimiter:
    def __init__(self) -> None:
        self._mem: dict[str, tuple[int, float]] = {}

    async def count(self, key: str) -> int:
        r = await get_redis()
        if r is not None:
            try:
                v = await r.get("rl:" + key)
                return int(v or 0)
            except Exception:  # noqa: BLE001
                pass
        c, exp = self._mem.get(key, (0, 0.0))
        return c if exp > time.monotonic() else 0

    async def incr(self, key: str, window: int) -> int:
        r = await get_redis()
        if r is not None:
            try:
                n = await r.incr("rl:" + key)
                if n == 1:
                    await r.expire("rl:" + key, window)
                return int(n)
            except Exception:  # noqa: BLE001
                pass
        now = time.monotonic()
        c, exp = self._mem.get(key, (0, 0.0))
        if exp <= now:
            c, exp = 0, now + window
        c += 1
        self._mem[key] = (c, exp)
        if len(self._mem) > 10000:
            self._mem = {k: v for k, v in self._mem.items() if v[1] > now}
        return c

    async def reset(self, key: str) -> None:
        self._mem.pop(key, None)
        r = await get_redis()
        if r is not None:
            try:
                await r.delete("rl:" + key)
            except Exception:  # noqa: BLE001
                pass

    def clear(self) -> None:
        self._mem.clear()


limiter = RateLimiter()
