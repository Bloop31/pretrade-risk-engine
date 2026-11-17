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
from risk_service.state.keys import positions_key
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


@pytest.fixture
async def prices(redis: FakeAsyncRedis) -> PriceStore:
    store = PriceStore(redis)
    await store.set("AAPL", D(100))
    return store


@pytest.fixture
def service(
    redis: FakeAsyncRedis, rules: RuleSet, accounts: AccountStore, prices: PriceStore
) -> PreTradeService:
    return PreTradeService(
        engine=RiskEngine(),
        rules=lambda: rules,
        accounts=accounts,
        prices=prices,
        rate_limiter=RateLimiter(redis),
    )


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
