"""The same guarantees, against a real Redis server.

fakeredis runs commands without yielding to the event loop, so concurrent
tests there never truly interleave. These do. They run only when
``REDIS_TEST_URL`` is set (CI uses a redis:7 service container), and refuse to
touch a database that is not empty.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from redis.asyncio import Redis

from risk_service.domain.engine import RiskEngine
from risk_service.domain.models import Decision, Side
from risk_service.rules.loader import parse_rules
from risk_service.services.pretrade import PreTradeService
from risk_service.state.accounts import AccountStore
from risk_service.state.prices import PriceStore
from risk_service.state.rate import RateLimiter
from tests.factories import make_order
from tests.metrics import sample

REDIS_URL = os.environ.get("REDIS_TEST_URL")

pytestmark = [
    pytest.mark.redis,
    pytest.mark.skipif(not REDIS_URL, reason="set REDIS_TEST_URL to run against a real Redis"),
]

D = Decimal

RULES = parse_rules(b"""\
schema_version: 1
defaults:
  max_order_quantity: 1000
  max_order_notional: 1000000
  price_collar_pct: 5
  max_position: 5000
  max_gross_exposure: 100000000
  max_orders_per_second: 100000
""")


@pytest.fixture
async def real_redis() -> AsyncIterator[Redis]:
    assert REDIS_URL is not None
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    if await client.dbsize():
        await client.aclose()
        pytest.fail(f"{REDIS_URL} is not empty; refusing to run destructive tests against it")
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def service(real_redis: Redis) -> PreTradeService:
    prices = PriceStore(real_redis)
    await prices.set("AAPL", D(100))
    return PreTradeService(
        engine=RiskEngine(),
        rules=lambda: RULES,
        accounts=AccountStore(real_redis, max_attempts=200),
        prices=prices,
        rate_limiter=RateLimiter(real_redis),
    )


async def test_concurrent_orders_cannot_jointly_breach_a_limit(
    service: PreTradeService, real_redis: Redis
) -> None:
    conflicts_before = sample("risk_reservation_conflicts_total")
    orders = [make_order(client_order_id=f"o{i}", quantity=D(1000)) for i in range(50)]

    decisions = await asyncio.gather(*(service.check(o) for o in orders))

    accepted = [d for d in decisions if d.decision is Decision.ACCEPT]
    assert len(accepted) == 5
    snapshot = await AccountStore(real_redis).snapshot("ACC-1")
    assert snapshot.open_buys == {"AAPL": D(5000)}
    # Every coroutine WATCHes the same keys and then awaits network I/O, so the
    # first EXEC must invalidate others: proof the race was really exercised.
    assert sample("risk_reservation_conflicts_total") > conflicts_before


async def test_concurrent_fills_and_cancels_keep_books_consistent(
    service: PreTradeService, real_redis: Redis
) -> None:
    store = AccountStore(real_redis, max_attempts=200)
    for i in range(20):
        side = Side.BUY if i % 2 == 0 else Side.SELL
        order = make_order(client_order_id=f"o{i}", side=side, quantity=D(100))
        assert (await service.check(order)).decision is Decision.ACCEPT

    async def settle(i: int) -> None:
        if i < 10:
            await store.apply_fill("ACC-1", f"o{i}", D(60))
            await store.apply_fill("ACC-1", f"o{i}", D(40))
        else:
            await store.apply_fill("ACC-1", f"o{i}", D(25))
            await store.release("ACC-1", f"o{i}")

    await asyncio.gather(*(settle(i) for i in range(20)))

    snapshot = await store.snapshot("ACC-1")
    # o0..o9 fully filled: 5 buys and 5 sells of 100 net to 0.
    # o10..o19 filled 25 each then cancelled: 5 buys and 5 sells of 25 net to 0.
    assert snapshot.positions == {}
    assert snapshot.open_buys == {}
    assert snapshot.open_sells == {}


async def test_rate_limit_under_concurrency(real_redis: Redis) -> None:
    limiter = RateLimiter(real_redis, window_ms=60_000)
    counts = await asyncio.gather(*(limiter.hit("ACC-1") for _ in range(100)))
    assert sorted(counts) == list(range(1, 101))
