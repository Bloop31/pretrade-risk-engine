"""Boundary tests for each check. Limits are inclusive: exactly-at-limit passes."""

from decimal import Decimal

import pytest

from risk_service.domain.checks import (
    max_gross_exposure,
    max_order_notional,
    max_order_quantity,
    max_position,
    order_rate,
    price_collar,
    restricted_symbol,
    trading_enabled,
)
from risk_service.domain.models import CheckStatus, OrderType, Side
from tests.factories import make_ctx, make_order

D = Decimal
PASS, FAIL, SKIPPED = CheckStatus.PASS, CheckStatus.FAIL, CheckStatus.SKIPPED


class TestTradingEnabled:
    def test_pass(self) -> None:
        assert trading_enabled(make_ctx()).status is PASS

    @pytest.mark.parametrize(
        ("halted_by", "reason"), [("global", "all accounts"), ("account", "ACC-1")]
    )
    def test_halted(self, halted_by: str, reason: str) -> None:
        result = trading_enabled(make_ctx(trading_halted_by=halted_by))
        assert result.status is FAIL
        assert result.reason is not None
        assert reason in result.reason


class TestRestrictedSymbol:
    def test_pass(self) -> None:
        assert restricted_symbol(make_ctx()).status is PASS

    def test_fail(self) -> None:
        result = restricted_symbol(make_ctx(symbol_restricted=True))
        assert result.status is FAIL
        assert result.reason == "AAPL is on the restricted list"


class TestOrderRate:
    @pytest.mark.parametrize(("count", "status"), [(1, PASS), (10, PASS), (11, FAIL)])
    def test_boundary(self, count: int, status: CheckStatus) -> None:
        result = order_rate(make_ctx(orders_in_window=count, max_orders_per_second=10))
        assert result.status is status
        assert result.value == D(count)
        assert result.limit == D(10)


class TestMaxOrderQuantity:
    @pytest.mark.parametrize(
        ("quantity", "status"), [("999.99", PASS), ("1000", PASS), ("1000.0001", FAIL)]
    )
    def test_boundary(self, quantity: str, status: CheckStatus) -> None:
        ctx = make_ctx(make_order(quantity=D(quantity), price=D("1")))
        assert max_order_quantity(ctx).status is status


class TestMaxOrderNotional:
    @pytest.mark.parametrize(("price", "status"), [("1000", PASS), ("1000.01", FAIL)])
    def test_limit_order_uses_limit_price(self, price: str, status: CheckStatus) -> None:
        # 100 x 1000 = 100000 = limit
        ctx = make_ctx(make_order(quantity=D(100), price=D(price)), reference_price=D(1))
        result = max_order_notional(ctx)
        assert result.status is status
        assert result.value == D(100) * D(price)

    def test_market_order_uses_reference_price(self) -> None:
        order = make_order(order_type=OrderType.MARKET, quantity=D(100))
        assert max_order_notional(make_ctx(order, reference_price=D(1000))).status is PASS
        assert max_order_notional(make_ctx(order, reference_price=D("1000.01"))).status is FAIL

    def test_market_order_without_reference_price_fails_closed(self) -> None:
        order = make_order(order_type=OrderType.MARKET)
        result = max_order_notional(make_ctx(order, reference_price=None))
        assert result.status is FAIL
        assert result.reason is not None
        assert "no reference price" in result.reason

    def test_no_float_rounding(self) -> None:
        # 3 x 0.1 is exactly 0.3 in Decimal (0.30000000000000004 in float).
        ctx = make_ctx(make_order(quantity=D(3), price=D("0.1")), max_order_notional=D("0.3"))
        result = max_order_notional(ctx)
        assert result.status is PASS
        assert result.value == D("0.3")


class TestPriceCollar:
    @pytest.mark.parametrize(
        ("price", "status"),
        [("105", PASS), ("95", PASS), ("105.0001", FAIL), ("94.9999", FAIL), ("100", PASS)],
    )
    def test_boundary(self, price: str, status: CheckStatus) -> None:
        ctx = make_ctx(make_order(price=D(price)), reference_price=D(100), price_collar_pct=D(5))
        assert price_collar(ctx).status is status

    def test_reports_deviation(self) -> None:
        result = price_collar(make_ctx(make_order(price=D("110")), reference_price=D(100)))
        assert result.value == D("10.0000")
        assert result.reason is not None
        assert "10.0000%" in result.reason

    def test_market_orders_are_skipped(self) -> None:
        result = price_collar(make_ctx(make_order(order_type=OrderType.MARKET)))
        assert result.status is SKIPPED

    @pytest.mark.parametrize("reference", [None, D(0)])
    def test_missing_reference_fails_closed(self, reference: Decimal | None) -> None:
        assert price_collar(make_ctx(reference_price=reference)).status is FAIL


class TestMaxPosition:
    @pytest.mark.parametrize(
        ("position", "side", "quantity", "status"),
        [
            ("4900", Side.BUY, "100", PASS),  # lands exactly on +5000
            ("4900", Side.BUY, "101", FAIL),
            ("-4900", Side.SELL, "100", PASS),  # lands exactly on -5000
            ("-4900", Side.SELL, "101", FAIL),
            ("4900", Side.SELL, "1000", PASS),
            ("0", Side.SELL, "1000", PASS),  # opening a short within the limit
        ],
    )
    def test_boundary(self, position: str, side: Side, quantity: str, status: CheckStatus) -> None:
        ctx = make_ctx(make_order(side=side, quantity=D(quantity)), position=D(position))
        assert max_position(ctx).status is status

    def test_reducing_order_allowed_when_already_over_limit(self) -> None:
        ctx = make_ctx(make_order(side=Side.SELL, quantity=D(100)), position=D(8000))
        assert max_position(ctx).status is PASS

    def test_increasing_order_rejected_when_already_over_limit(self) -> None:
        ctx = make_ctx(make_order(side=Side.BUY, quantity=D(1)), position=D(8000))
        assert max_position(ctx).status is FAIL

    def test_flipping_through_zero_beyond_limit_fails(self) -> None:
        # long 1000 -> short 5001 is not "reducing": |-5001| > |1000|
        ctx = make_ctx(make_order(side=Side.SELL, quantity=D(6001)), position=D(1000))
        assert max_position(ctx).status is FAIL


class TestMaxGrossExposure:
    def test_exactly_at_limit_passes(self) -> None:
        # +100 shares x 100 = +10000 on top of 990000 -> 1000000
        ctx = make_ctx(gross_exposure=D(990000))
        result = max_gross_exposure(ctx)
        assert result.status is PASS
        assert result.value == D(1000000)

    def test_just_over_limit_fails(self) -> None:
        ctx = make_ctx(gross_exposure=D("990000.01"))
        assert max_gross_exposure(ctx).status is FAIL

    def test_reducing_order_allowed_when_over_limit(self) -> None:
        order = make_order(side=Side.SELL, quantity=D(100))
        ctx = make_ctx(order, position=D(500), gross_exposure=D(2000000))
        result = max_gross_exposure(ctx)
        assert result.status is PASS
        assert result.value == D(2000000) - D(10000)

    def test_flip_counts_only_net_change(self) -> None:
        # long 50 -> short 50: |pos| unchanged, exposure delta is zero
        order = make_order(side=Side.SELL, quantity=D(100))
        ctx = make_ctx(order, position=D(50), gross_exposure=D(2000000))
        assert max_gross_exposure(ctx).status is PASS

    def test_market_without_reference_price_fails_closed(self) -> None:
        order = make_order(order_type=OrderType.MARKET)
        assert max_gross_exposure(make_ctx(order, reference_price=None)).status is FAIL
