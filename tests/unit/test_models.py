import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from risk_service.domain.models import (
    CheckResult,
    CheckStatus,
    Decision,
    Order,
    OrderType,
    RiskDecision,
    Side,
)
from tests.factories import make_order

LIMIT_ORDER_JSON = {
    "client_order_id": "ord-1",
    "account": "ACC-1",
    "symbol": "aapl",
    "side": "BUY",
    "order_type": "LIMIT",
    "quantity": "100",
    "price": "187.25",
}


def test_order_from_json_normalises_symbol_and_keeps_decimals() -> None:
    order = Order.model_validate_json(json.dumps(LIMIT_ORDER_JSON))
    assert order.symbol == "AAPL"
    assert order.price == Decimal("187.25")
    assert isinstance(order.quantity, Decimal)


def test_high_precision_decimal_strings_are_exact() -> None:
    order = Order.model_validate({**LIMIT_ORDER_JSON, "price": "0.1000000000000000055"})
    assert order.price == Decimal("0.1000000000000000055")


@pytest.mark.parametrize("number", ["187.25", "0.1000000000000000055", "1e3"])
def test_json_fractional_numbers_are_rejected(number: str) -> None:
    # The JSON parser would hand us a float that has already been rounded.
    payload = json.dumps(LIMIT_ORDER_JSON).replace('"187.25"', number)
    with pytest.raises(ValidationError, match="must be sent as strings"):
        Order.model_validate_json(payload)


def test_json_integers_are_accepted() -> None:
    payload = json.dumps(LIMIT_ORDER_JSON).replace('"100"', "12345678901234567890123")
    assert Order.model_validate_json(payload).quantity == Decimal("12345678901234567890123")


def test_python_floats_are_rejected() -> None:
    with pytest.raises(ValidationError, match="must be sent as strings"):
        make_order(price=0.1)


@pytest.mark.parametrize("bad", ["0", "-1", "NaN", "Infinity", "abc"])
def test_quantity_must_be_positive_finite(bad: str) -> None:
    with pytest.raises(ValidationError):
        Order.model_validate({**LIMIT_ORDER_JSON, "quantity": bad})


def test_limit_order_requires_price() -> None:
    with pytest.raises(ValidationError, match="price is required for LIMIT"):
        Order.model_validate({**LIMIT_ORDER_JSON, "price": None})


def test_market_order_rejects_price() -> None:
    with pytest.raises(ValidationError, match="must not be set for MARKET"):
        Order.model_validate({**LIMIT_ORDER_JSON, "order_type": "MARKET"})


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        Order.model_validate({**LIMIT_ORDER_JSON, "qty": "5"})


@pytest.mark.parametrize("symbol", ["", "A" * 33, "AA PL", "-AAPL"])
def test_invalid_symbols(symbol: str) -> None:
    with pytest.raises(ValidationError):
        Order.model_validate({**LIMIT_ORDER_JSON, "symbol": symbol})


@pytest.mark.parametrize(("side", "expected"), [(Side.BUY, "100"), (Side.SELL, "-100")])
def test_signed_quantity(side: Side, expected: str) -> None:
    assert make_order(side=side).signed_quantity == Decimal(expected)


def test_order_is_immutable() -> None:
    order = make_order()
    with pytest.raises(ValidationError):
        order.quantity = Decimal("5")  # type: ignore[misc]


def test_decimals_serialise_as_plain_strings() -> None:
    result = CheckResult.passed("x", limit=Decimal("1E+6"), value=Decimal("0.00012"))
    dumped = json.loads(result.model_dump_json())
    assert dumped["limit"] == "1000000"
    assert dumped["value"] == "0.00012"


def _decision(*statuses: CheckStatus) -> RiskDecision:
    checks = tuple(CheckResult(check=f"c{i}", status=s) for i, s in enumerate(statuses))
    return RiskDecision.from_checks(make_order(), checks, "v1")


def test_decision_accepts_when_nothing_fails() -> None:
    decision = _decision(CheckStatus.PASS, CheckStatus.SKIPPED)
    assert decision.decision is Decision.ACCEPT
    assert decision.failed_checks == ()


def test_decision_rejects_on_any_failure() -> None:
    decision = _decision(CheckStatus.PASS, CheckStatus.FAIL)
    assert decision.decision is Decision.REJECT
    assert [c.check for c in decision.failed_checks] == ["c1"]


def test_decision_with_no_checks_fails_closed() -> None:
    assert _decision().decision is Decision.REJECT


def test_inconsistent_decision_cannot_be_constructed() -> None:
    with pytest.raises(ValidationError, match="inconsistent"):
        RiskDecision(
            client_order_id="ord-1",
            account="ACC-1",
            symbol="AAPL",
            decision=Decision.ACCEPT,
            rules_version="v1",
            checks=(CheckResult.failed("c", "nope"),),
        )


def test_market_order_factory_has_no_price() -> None:
    order = make_order(order_type=OrderType.MARKET)
    assert order.price is None
