from risk_service.domain.checks.base import CheckContext, risk_check
from risk_service.domain.models import CheckResult

NAME = "max_order_quantity"


@risk_check(NAME)
def max_order_quantity(ctx: CheckContext) -> CheckResult:
    """Fat-finger guard on the size of a single order."""
    limit = ctx.limits.max_order_quantity
    quantity = ctx.order.quantity
    if quantity <= limit:
        return CheckResult.passed(NAME, limit=limit, value=quantity)
    return CheckResult.failed(
        NAME, f"quantity {quantity} exceeds the limit of {limit}", limit=limit, value=quantity
    )
