"""Reference prices, used for notional, price-collar and exposure checks."""

from collections.abc import Iterable
from decimal import Decimal

from redis.asyncio import Redis

from risk_service.state.codec import decode, decode_hash, encode, text, text_hash
from risk_service.state.keys import PRICES_KEY


class PriceStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def set(self, symbol: str, price: Decimal) -> None:
        if not price.is_finite() or price <= 0:
            raise ValueError(f"price must be a positive finite number, got {price}")
        await self._redis.hset(PRICES_KEY, symbol, encode(price))

    async def get(self, symbol: str) -> Decimal | None:
        raw = text(await self._redis.hget(PRICES_KEY, symbol))
        return None if raw is None else decode(raw, key=f"{PRICES_KEY}[{symbol}]")

    async def get_many(self, symbols: Iterable[str]) -> dict[str, Decimal]:
        """Prices for the given symbols; symbols without a price are omitted."""
        wanted = sorted(set(symbols))
        if not wanted:
            return {}
        raw = [text(v) for v in await self._redis.hmget(PRICES_KEY, wanted)]
        return {
            symbol: decode(value, key=f"{PRICES_KEY}[{symbol}]")
            for symbol, value in zip(wanted, raw, strict=True)
            if value is not None
        }

    async def all(self) -> dict[str, Decimal]:
        raw = text_hash(await self._redis.hgetall(PRICES_KEY))
        return decode_hash(raw, key=PRICES_KEY)
