from decimal import Decimal

from risk_service.domain.checks.base import CheckContext, risk_check
from risk_service.domain.models import CheckResult, OrderType

NAME = "price_collar"

_HUNDRED = Decimal(100)
_REPORT_PRECISION = Decimal("0.0001")


@risk_check(NAME)
def price_collar(ctx: CheckContext) -> CheckResult:
    """A LIMIT price must be within ``price_collar_pct`` percent of the reference price."""
    if ctx.order.order_type is OrderType.MARKET:
        return CheckResult.skipped(NAME, "not applicable to MARKET orders")

    limit = ctx.limits.price_collar_pct
    reference = ctx.reference_price
    if reference is None or reference <= 0:
        return CheckResult.failed(
            NAME, f"no reference price for {ctx.order.symbol} to collar against", limit=limit
        )

    price = ctx.order.price
    if price is None:  # unreachable: Order guarantees LIMIT orders carry a price
        return CheckResult.failed(NAME, "LIMIT order has no price", limit=limit)

    deviation_pct = abs(price - reference) / reference * _HUNDRED
    reported = deviation_pct.quantize(_REPORT_PRECISION)
    if deviation_pct <= limit:
        return CheckResult.passed(NAME, limit=limit, value=reported)
    return CheckResult.failed(
        NAME,
        f"price {price} is {reported}% from the reference price {reference}, "
        f"outside the {limit}% collar",
        limit=limit,
        value=reported,
    )
