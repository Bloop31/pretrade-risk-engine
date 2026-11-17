from decimal import Decimal

import pytest
from fakeredis import FakeAsyncRedis

from risk_service.state.errors import CorruptStateError
from risk_service.state.keys import PRICES_KEY, PRICES_UPDATED_KEY
from risk_service.state.prices import PriceStore, Quote

NOW_MS = 1_700_000_000_123


@pytest.fixture
def prices(redis: FakeAsyncRedis) -> PriceStore:
    return PriceStore(redis, clock=lambda: NOW_MS)


async def test_round_trip_is_exact_and_timestamped(prices: PriceStore) -> None:
    written = await prices.set("AAPL", Decimal("187.123456789012345678"))
    assert written == Quote(price=Decimal("187.123456789012345678"), updated_at_ms=NOW_MS)
    assert await prices.get("AAPL") == written


async def test_missing_price(prices: PriceStore) -> None:
    assert await prices.get("NOPE") is None


async def test_get_many_omits_missing(prices: PriceStore) -> None:
    await prices.set("AAPL", Decimal(1))
    await prices.set("MSFT", Decimal(2))
    quotes = await prices.get_many(["AAPL", "MSFT", "NOPE"])
    assert {s: q.price for s, q in quotes.items()} == {"AAPL": Decimal(1), "MSFT": Decimal(2)}
    assert await prices.get_many([]) == {}


async def test_all(prices: PriceStore) -> None:
    await prices.set("AAPL", Decimal(1))
    assert await prices.all() == {"AAPL": Quote(Decimal(1), NOW_MS)}


async def test_untimestamped_price_has_unknown_age(
    prices: PriceStore, redis: FakeAsyncRedis
) -> None:
    await redis.hset(PRICES_KEY, "OLD", "5")
    assert await prices.get("OLD") == Quote(price=Decimal(5), updated_at_ms=None)


@pytest.mark.parametrize("bad", [Decimal(0), Decimal(-1), Decimal("NaN"), Decimal("Infinity")])
async def test_rejects_invalid_prices(prices: PriceStore, bad: Decimal) -> None:
    with pytest.raises(ValueError, match="positive finite"):
        await prices.set("AAPL", bad)


async def test_corrupt_price_is_detected(prices: PriceStore, redis: FakeAsyncRedis) -> None:
    await redis.hset(PRICES_KEY, "AAPL", "not-a-number")
    with pytest.raises(CorruptStateError, match="AAPL"):
        await prices.get("AAPL")


async def test_corrupt_timestamp_is_detected(prices: PriceStore, redis: FakeAsyncRedis) -> None:
    await prices.set("AAPL", Decimal(1))
    await redis.hset(PRICES_UPDATED_KEY, "AAPL", "yesterday")
    with pytest.raises(CorruptStateError, match="yesterday"):
        await prices.get("AAPL")
