from risk_service.domain.checks.base import CheckContext, risk_check
from risk_service.domain.models import CheckResult

NAME = "max_order_notional"


@risk_check(NAME)
def max_order_notional(ctx: CheckContext) -> CheckResult:
    """Fat-finger guard on the value of a single order (quantity x price)."""
    limit = ctx.limits.max_order_notional
    price = ctx.valuation_price
    if price is None:
        return CheckResult.failed(
            NAME, f"no reference price for {ctx.order.symbol} to value a MARKET order", limit=limit
        )
    notional = ctx.order.quantity * price
    if notional <= limit:
        return CheckResult.passed(NAME, limit=limit, value=notional)
    return CheckResult.failed(
        NAME, f"notional {notional} exceeds the limit of {limit}", limit=limit, value=notional
    )
