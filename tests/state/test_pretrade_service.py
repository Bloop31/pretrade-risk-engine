"""The full check path (rules + engine + Redis state), against fakeredis."""

import asyncio
from decimal import Decimal

import pytest
from fakeredis import FakeAsyncRedis
from redis.exceptions import ConnectionError as RedisConnectionError

from risk_service.domain.engine import RiskEngine
from risk_service.domain.models import Decision, OrderType, Side
from risk_service.rules.loader import parse_rules
from risk_service.rules.ruleset import RuleSet
from risk_service.services.pretrade import STATE_CHECK, PreTradeService
from risk_service.state.accounts import AccountStore
from risk_service.state.errors import DuplicateOrderError
from risk_service.state.keys import PRICES_KEY, positions_key
from risk_service.state.prices import PriceStore
from risk_service.state.rate import RateLimiter
from tests.factories import make_order

D = Decimal

RULES = b"""\
schema_version: 1
defaults:
  max_order_quantity: 1000
  max_order_notional: 1000000
  price_collar_pct: 5
  max_position: 5000
  max_gross_exposure: 10000000
  max_orders_per_second: 1000
  max_price_age_seconds: 30
accounts:
  SLOW:
    max_orders_per_second: 2
"""


@pytest.fixture
def rules() -> RuleSet:
    return parse_rules(RULES)


@pytest.fixture
def accounts(redis: FakeAsyncRedis) -> AccountStore:
    return AccountStore(redis, max_attempts=100)


class FakeClock:
    def __init__(self) -> None:
        self.now_ms = 1_700_000_000_000

    def __call__(self) -> int:
        return self.now_ms


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def prices(redis: FakeAsyncRedis, clock: FakeClock) -> PriceStore:
    store = PriceStore(redis, clock=clock)
    await store.set("AAPL", D(100))
    return store


@pytest.fixture
def service(
    redis: FakeAsyncRedis,
    rules: RuleSet,
    accounts: AccountStore,
    prices: PriceStore,
    clock: FakeClock,
) -> PreTradeService:
    return PreTradeService(
        engine=RiskEngine(),
        rules=lambda: rules,
        accounts=accounts,
        prices=prices,
        rate_limiter=RateLimiter(redis, clock=clock),
        clock=clock,
    )


async def test_price_exactly_at_max_age_is_fresh(
    service: PreTradeService, clock: FakeClock
) -> None:
    clock.now_ms += 30_000
    decision = await service.check(make_order())
    assert decision.decision is Decision.ACCEPT


async def test_stale_price_rejects(
    service: PreTradeService, accounts: AccountStore, clock: FakeClock
) -> None:
    clock.now_ms += 30_001
    decision = await service.check(make_order())
    assert decision.decision is Decision.REJECT
    assert [c.check for c in decision.failed_checks] == ["reference_price_fresh"]
    assert (await accounts.snapshot("ACC-1")).open_buys == {}


async def test_untimestamped_price_rejects(service: PreTradeService, redis: FakeAsyncRedis) -> None:
    await redis.hset(PRICES_KEY, "MSFT", "400")  # written without a timestamp
    decision = await service.check(make_order(symbol="MSFT", price=D(400)))
    assert [c.check for c in decision.failed_checks] == ["reference_price_fresh"]


async def test_price_from_a_clock_ahead_of_ours_counts_as_fresh(
    service: PreTradeService, prices: PriceStore, clock: FakeClock
) -> None:
    clock.now_ms += 5_000
    await prices.set("AAPL", D(100))  # writer stamped at +5s
    clock.now_ms -= 5_000  # our clock is 5s behind the writer's
    assert (await service.check(make_order())).decision is Decision.ACCEPT


async def test_accept_reserves(service: PreTradeService, accounts: AccountStore) -> None:
    decision = await service.check(make_order(quantity=D(10)))
    assert decision.decision is Decision.ACCEPT
    assert (await accounts.snapshot("ACC-1")).open_buys == {"AAPL": D(10)}


async def test_open_orders_count_towards_position_limit(service: PreTradeService) -> None:
    for i in range(5):
        decision = await service.check(make_order(client_order_id=f"o{i}", quantity=D(1000)))
        assert decision.decision is Decision.ACCEPT
    sixth = await service.check(make_order(client_order_id="o5", quantity=D(1)))
    assert sixth.decision is Decision.REJECT
    assert [c.check for c in sixth.failed_checks] == ["max_position"]


async def test_concurrent_orders_cannot_jointly_breach_a_limit(
    service: PreTradeService, accounts: AccountStore
) -> None:
    orders = [make_order(client_order_id=f"o{i}", quantity=D(1000)) for i in range(20)]
    decisions = await asyncio.gather(*(service.check(o) for o in orders))

    accepted = [d for d in decisions if d.decision is Decision.ACCEPT]
    assert len(accepted) == 5  # 5 x 1000 = max_position
    assert (await accounts.snapshot("ACC-1")).open_buys == {"AAPL": D(5000)}


async def test_market_order_uses_stored_price(service: PreTradeService) -> None:
    decision = await service.check(make_order(order_type=OrderType.MARKET, quantity=D(10)))
    assert decision.decision is Decision.ACCEPT
    notional = next(c for c in decision.checks if c.check == "max_order_notional")
    assert notional.value == D(1000)


async def test_missing_reference_price_rejects_limit_order(service: PreTradeService) -> None:
    decision = await service.check(make_order(symbol="MSFT"))
    assert decision.decision is Decision.REJECT
    assert {c.check for c in decision.failed_checks} == {"price_collar"}


async def test_unpriced_holding_blocks_exposure_check(
    service: PreTradeService, accounts: AccountStore
) -> None:
    await accounts.set_position("ACC-1", "MSFT", D(10))
    decision = await service.check(make_order())
    assert {c.check for c in decision.failed_checks} == {"max_gross_exposure"}


async def test_reducing_sell_against_long_position(
    service: PreTradeService, accounts: AccountStore
) -> None:
    await accounts.set_position("ACC-1", "AAPL", D(6000))  # already over max_position
    sell = await service.check(make_order(side=Side.SELL, quantity=D(500)))
    buy = await service.check(make_order(client_order_id="o2", quantity=D(1)))
    assert sell.decision is Decision.ACCEPT
    assert buy.decision is Decision.REJECT


async def test_rate_limit_applies_per_account(service: PreTradeService) -> None:
    results = [
        await service.check(make_order(account="SLOW", client_order_id=f"o{i}", quantity=D(1)))
        for i in range(3)
    ]
    assert [r.decision for r in results] == [Decision.ACCEPT, Decision.ACCEPT, Decision.REJECT]
    assert [c.check for c in results[2].failed_checks] == ["order_rate"]


async def test_duplicate_client_order_id_raises(service: PreTradeService) -> None:
    await service.check(make_order(client_order_id="dup"))
    with pytest.raises(DuplicateOrderError):
        await service.check(make_order(client_order_id="dup"))


async def test_decision_carries_rules_version(service: PreTradeService, rules: RuleSet) -> None:
    assert (await service.check(make_order())).rules_version == rules.version


async def test_corrupt_state_fails_closed(service: PreTradeService, redis: FakeAsyncRedis) -> None:
    await redis.hset(positions_key("ACC-1"), "AAPL", "garbage")
    decision = await service.check(make_order())
    assert decision.decision is Decision.REJECT
    assert [c.check for c in decision.checks] == [STATE_CHECK]
    assert decision.checks[0].reason == "risk state unavailable: CorruptStateError"


async def test_redis_outage_fails_closed(
    rules: RuleSet, accounts: AccountStore, prices: PriceStore, redis: FakeAsyncRedis
) -> None:
    class DownRateLimiter(RateLimiter):
        async def hit(self, account: str) -> int:
            raise RedisConnectionError("connection refused")

    service = PreTradeService(
        engine=RiskEngine(),
        rules=lambda: rules,
        accounts=accounts,
        prices=prices,
        rate_limiter=DownRateLimiter(redis),
    )
    decision = await service.check(make_order())
    assert decision.decision is Decision.REJECT
    assert decision.checks[0].check == STATE_CHECK
