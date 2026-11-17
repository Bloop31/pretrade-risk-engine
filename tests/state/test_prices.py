from decimal import Decimal

import pytest
from fakeredis import FakeAsyncRedis

from risk_service.state.errors import CorruptStateError
from risk_service.state.keys import PRICES_KEY
from risk_service.state.prices import PriceStore


@pytest.fixture
def prices(redis: FakeAsyncRedis) -> PriceStore:
    return PriceStore(redis)


async def test_round_trip_is_exact(prices: PriceStore) -> None:
    await prices.set("AAPL", Decimal("187.123456789012345678"))
    assert await prices.get("AAPL") == Decimal("187.123456789012345678")


async def test_missing_price(prices: PriceStore) -> None:
    assert await prices.get("NOPE") is None


async def test_get_many_omits_missing(prices: PriceStore) -> None:
    await prices.set("AAPL", Decimal(1))
    await prices.set("MSFT", Decimal(2))
    assert await prices.get_many(["AAPL", "MSFT", "NOPE"]) == {
        "AAPL": Decimal(1),
        "MSFT": Decimal(2),
    }
    assert await prices.get_many([]) == {}


async def test_all(prices: PriceStore) -> None:
    await prices.set("AAPL", Decimal(1))
    assert await prices.all() == {"AAPL": Decimal(1)}


@pytest.mark.parametrize("bad", [Decimal(0), Decimal(-1), Decimal("NaN"), Decimal("Infinity")])
async def test_rejects_invalid_prices(prices: PriceStore, bad: Decimal) -> None:
    with pytest.raises(ValueError, match="positive finite"):
        await prices.set("AAPL", bad)


async def test_corrupt_value_is_detected(prices: PriceStore, redis: FakeAsyncRedis) -> None:
    await redis.hset(PRICES_KEY, "AAPL", "not-a-number")
    with pytest.raises(CorruptStateError, match="AAPL"):
        await prices.get("AAPL")
