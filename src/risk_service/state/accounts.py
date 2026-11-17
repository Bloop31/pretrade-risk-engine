"""Positions and open-order reservations, updated atomically.

Every read-modify-write runs as an optimistic ``WATCH``/``MULTI`` transaction
over the account's keys. If another writer touches those keys between our read
and our ``EXEC``, Redis aborts the transaction and we retry from a fresh read.
Arithmetic happens in Python on ``Decimal``; Redis only stores strings.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import Pipeline
from redis.exceptions import WatchError

from risk_service.domain.models import Decision, Order, RiskDecision, Side
from risk_service.domain.positions import AccountSnapshot
from risk_service.observability.metrics import RESERVATION_CONFLICTS
from risk_service.state.codec import ZERO, decode, decode_hash, encode, text, text_hash
from risk_service.state.errors import (
    CorruptStateError,
    DuplicateOrderError,
    OverfillError,
    StateContentionError,
    UnknownOrderError,
)
from risk_service.state.keys import open_field, open_orders_key, order_key, positions_key

Decide = Callable[[AccountSnapshot], Awaitable[RiskDecision]]

DEFAULT_MAX_ATTEMPTS = 20


@dataclass(frozen=True, slots=True)
class OpenOrder:
    client_order_id: str
    symbol: str
    side: Side
    quantity: Decimal
    remaining: Decimal


class AccountStore:
    def __init__(self, redis: Redis, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._redis = redis
        self._max_attempts = max_attempts

    # ------------------------------------------------------------------ reads

    async def snapshot(self, account: str) -> AccountSnapshot:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hgetall(positions_key(account))
            pipe.hgetall(open_orders_key(account))
            positions, open_orders = await pipe.execute()
        return _build_snapshot(account, text_hash(positions), text_hash(open_orders))

    async def get_open_order(self, account: str, client_order_id: str) -> OpenOrder | None:
        raw = text_hash(await self._redis.hgetall(order_key(account, client_order_id)))
        return _parse_order(client_order_id, raw, order_key(account, client_order_id))

    # ----------------------------------------------------------------- writes

    async def set_position(self, account: str, symbol: str, quantity: Decimal) -> None:
        """Overwrite the filled position (e.g. start-of-day load from the books)."""
        async with self._redis.pipeline(transaction=True) as pipe:
            _set_or_delete(pipe, positions_key(account), symbol, quantity)
            await pipe.execute()

    async def evaluate_and_reserve(self, order: Order, decide: Decide) -> RiskDecision:
        """Run ``decide`` on a consistent snapshot; if it ACCEPTs, reserve the order.

        The decision and the reservation commit together or not at all, so two
        concurrent orders can never both pass a limit that only one fits under.
        ``decide`` may be called more than once if the transaction is retried.
        """
        account = order.account
        pos_key, open_key = positions_key(account), open_orders_key(account)
        ord_key = order_key(account, order.client_order_id)

        async def attempt(pipe: Pipeline) -> RiskDecision:
            await pipe.watch(pos_key, open_key, ord_key)
            if await pipe.exists(ord_key):
                raise DuplicateOrderError(
                    f"order {order.client_order_id} is already open for account {account}"
                )
            positions = text_hash(await pipe.hgetall(pos_key))
            open_orders = text_hash(await pipe.hgetall(open_key))
            decision = await decide(_build_snapshot(account, positions, open_orders))
            if decision.decision is not Decision.ACCEPT:
                return decision

            field = open_field(order.side, order.symbol)
            reserved = decode(open_orders.get(field), key=f"{open_key}[{field}]")
            _begin(pipe)
            pipe.hset(open_key, field, encode(reserved + order.quantity))
            pipe.hset(
                ord_key,
                mapping={
                    "symbol": order.symbol,
                    "side": order.side.value,
                    "quantity": encode(order.quantity),
                    "remaining": encode(order.quantity),
                    "rules_version": decision.rules_version,
                },
            )
            await pipe.execute()
            return decision

        return await self._transact(attempt)

    async def apply_fill(self, account: str, client_order_id: str, quantity: Decimal) -> Decimal:
        """Move ``quantity`` of an open order into the filled position.

        Returns the order's remaining quantity; at zero the order is closed.
        """
        if quantity <= 0:
            raise ValueError("fill quantity must be positive")

        async def attempt(pipe: Pipeline) -> Decimal:
            order, pos_key, open_key, ord_key = await self._watch_order(
                pipe, account, client_order_id
            )
            if quantity > order.remaining:
                raise OverfillError(
                    f"fill of {quantity} exceeds remaining {order.remaining} "
                    f"on order {client_order_id}"
                )
            field = open_field(order.side, order.symbol)
            position = decode(text(await pipe.hget(pos_key, order.symbol)), key=pos_key)
            reserved = decode(text(await pipe.hget(open_key, field)), key=open_key)
            signed = quantity if order.side is Side.BUY else -quantity
            remaining = order.remaining - quantity

            _begin(pipe)
            _set_or_delete(pipe, pos_key, order.symbol, position + signed)
            _set_or_delete(pipe, open_key, field, max(reserved - quantity, ZERO))
            if remaining == 0:
                pipe.delete(ord_key)
            else:
                pipe.hset(ord_key, "remaining", encode(remaining))
            await pipe.execute()
            return remaining

        return await self._transact(attempt)

    async def release(self, account: str, client_order_id: str) -> Decimal:
        """Cancel the unfilled remainder of an order; returns the quantity released."""

        async def attempt(pipe: Pipeline) -> Decimal:
            order, _, open_key, ord_key = await self._watch_order(pipe, account, client_order_id)
            field = open_field(order.side, order.symbol)
            reserved = decode(text(await pipe.hget(open_key, field)), key=open_key)

            _begin(pipe)
            _set_or_delete(pipe, open_key, field, max(reserved - order.remaining, ZERO))
            pipe.delete(ord_key)
            await pipe.execute()
            return order.remaining

        return await self._transact(attempt)

    # --------------------------------------------------------------- internals

    async def _transact[T](self, attempt: Callable[[Pipeline], Awaitable[T]]) -> T:
        for _ in range(self._max_attempts):
            async with self._redis.pipeline(transaction=True) as pipe:
                try:
                    return await attempt(pipe)
                except WatchError:
                    RESERVATION_CONFLICTS.inc()
                    continue
        raise StateContentionError(f"gave up after {self._max_attempts} conflicting attempts")

    @staticmethod
    async def _watch_order(
        pipe: Pipeline, account: str, client_order_id: str
    ) -> tuple[OpenOrder, str, str, str]:
        pos_key, open_key = positions_key(account), open_orders_key(account)
        ord_key = order_key(account, client_order_id)
        await pipe.watch(pos_key, open_key, ord_key)
        raw = text_hash(await pipe.hgetall(ord_key))
        order = _parse_order(client_order_id, raw, ord_key)
        if order is None:
            raise UnknownOrderError(f"no open order {client_order_id} for account {account}")
        return order, pos_key, open_key, ord_key


def _begin(pipe: Pipeline) -> None:
    """Switch a watching pipeline from immediate reads to queued ``MULTI`` writes."""
    pipe.multi()  # type: ignore[no-untyped-call]  # redis-py leaves multi() unannotated


def _set_or_delete(pipe: Pipeline, key: str, field: str, value: Decimal) -> None:
    # Keep hashes small: a flat position or fully released side is just absent.
    if value == 0:
        pipe.hdel(key, field)
    else:
        pipe.hset(key, field, encode(value))


def _build_snapshot(
    account: str, positions: dict[str, str], open_orders: dict[str, str]
) -> AccountSnapshot:
    open_buys: dict[str, Decimal] = {}
    open_sells: dict[str, Decimal] = {}
    key = open_orders_key(account)
    for name, quantity in decode_hash(open_orders, key=key).items():
        side, _, symbol = name.partition(":")
        if side == Side.BUY.value:
            open_buys[symbol] = quantity
        elif side == Side.SELL.value:
            open_sells[symbol] = quantity
        else:
            raise CorruptStateError(f"{key}: unexpected field {name!r}")
    return AccountSnapshot(
        positions=decode_hash(positions, key=positions_key(account)),
        open_buys=open_buys,
        open_sells=open_sells,
    )


def _parse_order(client_order_id: str, raw: dict[str, Any], key: str) -> OpenOrder | None:
    if not raw:
        return None
    try:
        return OpenOrder(
            client_order_id=client_order_id,
            symbol=raw["symbol"],
            side=Side(raw["side"]),
            quantity=decode(raw["quantity"], key=key),
            remaining=decode(raw["remaining"], key=key),
        )
    except (KeyError, ValueError) as exc:
        raise CorruptStateError(f"{key}: malformed order record") from exc
