from decimal import Decimal

import pytest
from fakeredis import FakeAsyncRedis

from risk_service.domain.models import CheckResult, Order, RiskDecision, Side
from risk_service.domain.positions import AccountSnapshot
from risk_service.state.accounts import AccountStore
from risk_service.state.errors import (
    CorruptStateError,
    DuplicateOrderError,
    OverfillError,
    StateContentionError,
    UnknownOrderError,
)
from risk_service.state.keys import open_orders_key, order_key, positions_key
from tests.factories import make_order

D = Decimal


@pytest.fixture
def store(redis: FakeAsyncRedis) -> AccountStore:
    return AccountStore(redis)


def _accept(order: Order) -> RiskDecision:
    return RiskDecision.from_checks(order, (CheckResult.passed("ok"),), "v1")


def _reject(order: Order) -> RiskDecision:
    return RiskDecision.from_checks(order, (CheckResult.failed("no", "nope"),), "v1")


async def _reserve(store: AccountStore, order: Order) -> RiskDecision:
    async def decide(snapshot: AccountSnapshot) -> RiskDecision:
        return _accept(order)

    return await store.evaluate_and_reserve(order, decide)


async def test_empty_account(store: AccountStore) -> None:
    assert await store.snapshot("ACC-1") == AccountSnapshot()


async def test_set_position_and_flatten(store: AccountStore, redis: FakeAsyncRedis) -> None:
    await store.set_position("ACC-1", "AAPL", D("-12.5"))
    assert (await store.snapshot("ACC-1")).positions == {"AAPL": D("-12.5")}

    await store.set_position("ACC-1", "AAPL", D(0))
    assert await redis.hgetall(positions_key("ACC-1")) == {}


async def test_accept_reserves_open_quantity(store: AccountStore) -> None:
    await _reserve(store, make_order(client_order_id="o1", quantity=D(100)))
    await _reserve(store, make_order(client_order_id="o2", quantity=D(50)))
    await _reserve(store, make_order(client_order_id="o3", side=Side.SELL, quantity=D(7)))

    snap = await store.snapshot("ACC-1")
    assert snap.open_buys == {"AAPL": D(150)}
    assert snap.open_sells == {"AAPL": D(7)}
    open_order = await store.get_open_order("ACC-1", "o1")
    assert open_order is not None
    assert open_order.remaining == D(100)


async def test_reject_reserves_nothing(store: AccountStore) -> None:
    order = make_order()

    async def decide(snapshot: AccountSnapshot) -> RiskDecision:
        return _reject(order)

    await store.evaluate_and_reserve(order, decide)
    assert await store.snapshot("ACC-1") == AccountSnapshot()
    assert await store.get_open_order("ACC-1", order.client_order_id) is None


async def test_decide_sees_current_state(store: AccountStore) -> None:
    await store.set_position("ACC-1", "AAPL", D(10))
    await _reserve(store, make_order(client_order_id="o1", quantity=D(5)))
    seen: list[AccountSnapshot] = []
    order = make_order(client_order_id="o2")

    async def decide(snapshot: AccountSnapshot) -> RiskDecision:
        seen.append(snapshot)
        return _reject(order)

    await store.evaluate_and_reserve(order, decide)
    assert seen == [AccountSnapshot(positions={"AAPL": D(10)}, open_buys={"AAPL": D(5)})]


async def test_duplicate_open_order_is_refused(store: AccountStore) -> None:
    await _reserve(store, make_order(client_order_id="o1"))
    with pytest.raises(DuplicateOrderError, match="o1"):
        await _reserve(store, make_order(client_order_id="o1"))


async def test_partial_then_full_fill(store: AccountStore) -> None:
    await _reserve(store, make_order(client_order_id="o1", quantity=D(100)))

    assert await store.apply_fill("ACC-1", "o1", D(40)) == D(60)
    snap = await store.snapshot("ACC-1")
    assert snap.positions == {"AAPL": D(40)}
    assert snap.open_buys == {"AAPL": D(60)}

    assert await store.apply_fill("ACC-1", "o1", D(60)) == D(0)
    snap = await store.snapshot("ACC-1")
    assert snap.positions == {"AAPL": D(100)}
    assert snap.open_buys == {}
    assert await store.get_open_order("ACC-1", "o1") is None


async def test_sell_fill_reduces_position(store: AccountStore) -> None:
    await store.set_position("ACC-1", "AAPL", D(100))
    await _reserve(store, make_order(client_order_id="s1", side=Side.SELL, quantity=D(30)))
    await store.apply_fill("ACC-1", "s1", D(30))
    assert (await store.snapshot("ACC-1")).positions == {"AAPL": D(70)}


async def test_overfill_is_refused(store: AccountStore) -> None:
    await _reserve(store, make_order(client_order_id="o1", quantity=D(10)))
    with pytest.raises(OverfillError):
        await store.apply_fill("ACC-1", "o1", D("10.01"))
    assert (await store.snapshot("ACC-1")).open_buys == {"AAPL": D(10)}


async def test_fill_must_be_positive(store: AccountStore) -> None:
    with pytest.raises(ValueError, match="positive"):
        await store.apply_fill("ACC-1", "o1", D(0))


async def test_fill_unknown_order(store: AccountStore) -> None:
    with pytest.raises(UnknownOrderError):
        await store.apply_fill("ACC-1", "missing", D(1))


async def test_release_unknown_order(store: AccountStore) -> None:
    with pytest.raises(UnknownOrderError):
        await store.release("ACC-1", "missing")


async def test_corrupt_order_record(store: AccountStore, redis: FakeAsyncRedis) -> None:
    await redis.hset(order_key("ACC-1", "o1"), mapping={"symbol": "AAPL", "side": "HOLD"})
    with pytest.raises(CorruptStateError, match="malformed"):
        await store.get_open_order("ACC-1", "o1")


async def test_release_frees_remaining(store: AccountStore) -> None:
    await _reserve(store, make_order(client_order_id="o1", quantity=D(100)))
    await _reserve(store, make_order(client_order_id="o2", quantity=D(25)))
    await store.apply_fill("ACC-1", "o1", D(30))

    assert await store.release("ACC-1", "o1") == D(70)

    snap = await store.snapshot("ACC-1")
    assert snap.open_buys == {"AAPL": D(25)}
    assert snap.positions == {"AAPL": D(30)}
    assert await store.get_open_order("ACC-1", "o1") is None


async def test_concurrent_write_forces_retry_on_fresh_state(
    store: AccountStore, other_redis: FakeAsyncRedis
) -> None:
    """Another writer changes the account mid-check: our EXEC must abort and re-decide."""
    order = make_order(client_order_id="o1", quantity=D(10))
    seen: list[AccountSnapshot] = []

    async def decide(snapshot: AccountSnapshot) -> RiskDecision:
        seen.append(snapshot)
        if len(seen) == 1:
            await other_redis.hset(positions_key("ACC-1"), "AAPL", "500")
        return _accept(order)

    await store.evaluate_and_reserve(order, decide)

    assert len(seen) == 2
    assert seen[0].positions == {}
    assert seen[1].positions == {"AAPL": D(500)}
    assert (await store.snapshot("ACC-1")).open_buys == {"AAPL": D(10)}


async def test_gives_up_under_endless_contention(
    redis: FakeAsyncRedis, other_redis: FakeAsyncRedis
) -> None:
    store = AccountStore(redis, max_attempts=3)
    order = make_order()
    calls = 0

    async def decide(snapshot: AccountSnapshot) -> RiskDecision:
        nonlocal calls
        calls += 1
        await other_redis.hset(positions_key("ACC-1"), "AAPL", str(calls))
        return _accept(order)

    with pytest.raises(StateContentionError):
        await store.evaluate_and_reserve(order, decide)
    assert calls == 3
    assert (await store.snapshot("ACC-1")).open_buys == {}


@pytest.mark.parametrize(
    ("key", "field", "value"),
    [
        (positions_key("ACC-1"), "AAPL", "garbage"),
        (open_orders_key("ACC-1"), "BUY:AAPL", "Infinity"),
        (open_orders_key("ACC-1"), "HOLD:AAPL", "1"),
    ],
)
async def test_corrupt_state_is_detected(
    store: AccountStore, redis: FakeAsyncRedis, key: str, field: str, value: str
) -> None:
    await redis.hset(key, field, value)
    with pytest.raises(CorruptStateError):
        await store.snapshot("ACC-1")


def test_max_attempts_must_be_positive(redis: FakeAsyncRedis) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        AccountStore(redis, max_attempts=0)
