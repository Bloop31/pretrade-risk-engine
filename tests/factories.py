"""Builders for domain objects with sensible defaults; override only what a test cares about."""

from dataclasses import replace
from decimal import Decimal
from typing import Any

from risk_service.domain.checks import CheckContext
from risk_service.domain.limits import EffectiveLimits
from risk_service.domain.models import Order, OrderType, Side

D = Decimal
ZERO = D("0")
HUNDRED = D("100")

DEFAULT_LIMITS = EffectiveLimits(
    max_order_quantity=D("1000"),
    max_order_notional=D("100000"),
    price_collar_pct=D("5"),
    max_position=D("5000"),
    max_gross_exposure=D("1000000"),
    max_orders_per_second=10,
    max_price_age_seconds=30,
)


def make_order(**overrides: Any) -> Order:
    fields: dict[str, Any] = {
        "client_order_id": "ord-1",
        "account": "ACC-1",
        "symbol": "AAPL",
        "side": Side.BUY,
        "order_type": OrderType.LIMIT,
        "quantity": D("100"),
        "price": D("100"),
    }
    fields.update(overrides)
    if fields["order_type"] is OrderType.MARKET and "price" not in overrides:
        fields["price"] = None
    return Order(**fields)


def make_ctx(
    order: Order | None = None,
    *,
    reference_price: Decimal | None = HUNDRED,
    reference_price_age_ms: int | None = 0,
    position: Decimal = ZERO,
    gross_exposure: Decimal | None = ZERO,
    orders_in_window: int = 1,
    **limit_overrides: Any,
) -> CheckContext:
    return CheckContext(
        order=order or make_order(),
        limits=replace(DEFAULT_LIMITS, **limit_overrides),
        reference_price=reference_price,
        reference_price_age_ms=reference_price_age_ms,
        position=position,
        gross_exposure=gross_exposure,
        orders_in_window=orders_in_window,
    )
