"""Reference prices, used for notional, price-collar and exposure checks.

Every price is stored with the time it was written, so the service can refuse
to trade on a price that has gone stale (a dead market-data feed).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from redis.asyncio import Redis

from risk_service.clock import Clock, now_ms
from risk_service.state.codec import decode, encode, text, text_hash
from risk_service.state.errors import CorruptStateError
from risk_service.state.keys import PRICES_KEY, PRICES_UPDATED_KEY


@dataclass(frozen=True, slots=True)
class Quote:
    price: Decimal
    updated_at_ms: int | None
    """Unix time in ms when the price was written; None for untimestamped legacy entries."""


class PriceStore:
    def __init__(self, redis: Redis, *, clock: Clock = now_ms) -> None:
        self._redis = redis
        self._clock = clock

    async def set(self, symbol: str, price: Decimal) -> Quote:
        if not price.is_finite() or price <= 0:
            raise ValueError(f"price must be a positive finite number, got {price}")
        updated_at = self._clock()
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hset(PRICES_KEY, symbol, encode(price))
            pipe.hset(PRICES_UPDATED_KEY, symbol, str(updated_at))
            await pipe.execute()
        return Quote(price=price, updated_at_ms=updated_at)

    async def get(self, symbol: str) -> Quote | None:
        return (await self.get_many([symbol])).get(symbol)

    async def get_many(self, symbols: Iterable[str]) -> dict[str, Quote]:
        """Quotes for the given symbols; symbols without a price are omitted."""
        wanted = sorted(set(symbols))
        if not wanted:
            return {}
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hmget(PRICES_KEY, wanted)
            pipe.hmget(PRICES_UPDATED_KEY, wanted)
            prices, updated = await pipe.execute()
        return {
            symbol: _quote(symbol, text(price), text(at))
            for symbol, price, at in zip(wanted, prices, updated, strict=True)
            if price is not None
        }

    async def all(self) -> dict[str, Quote]:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hgetall(PRICES_KEY)
            pipe.hgetall(PRICES_UPDATED_KEY)
            raw_prices, raw_updated = await pipe.execute()
        prices, updated = text_hash(raw_prices), text_hash(raw_updated)
        return {
            symbol: _quote(symbol, price, updated.get(symbol)) for symbol, price in prices.items()
        }


def _quote(symbol: str, price: str | None, updated_at: str | None) -> Quote:
    key = f"{PRICES_KEY}[{symbol}]"
    timestamp = None
    if updated_at is not None:
        try:
            timestamp = int(updated_at)
        except ValueError as exc:
            raise CorruptStateError(f"{PRICES_UPDATED_KEY}[{symbol}]: {updated_at!r}") from exc
    return Quote(price=decode(price, key=key), updated_at_ms=timestamp)
