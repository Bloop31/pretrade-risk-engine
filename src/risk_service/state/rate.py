"""Sliding-window order-rate counter, one sorted set per account.

Every order attempt is counted, accepted or not: the limit protects the
exchange connection from message floods, not just from accepted orders.
"""

import uuid

from redis.asyncio import Redis

from risk_service.clock import Clock, now_ms
from risk_service.state.keys import rate_key


class RateLimiter:
    def __init__(self, redis: Redis, *, window_ms: int = 1000, clock: Clock = now_ms) -> None:
        if window_ms <= 0:
            raise ValueError("window_ms must be positive")
        self._redis = redis
        self._window_ms = window_ms
        self._clock = clock

    async def hit(self, account: str) -> int:
        """Record one order for ``account``; return how many fall in the current window."""
        key = rate_key(account)
        now = self._clock()
        async with self._redis.pipeline(transaction=True) as pipe:
            # Window is (now - window, now]; anything at or before the edge drops out.
            pipe.zremrangebyscore(key, "-inf", now - self._window_ms)
            pipe.zadd(key, {uuid.uuid4().hex: now})
            pipe.zcard(key)
            pipe.pexpire(key, self._window_ms)
            results = await pipe.execute()
        return int(results[2])
