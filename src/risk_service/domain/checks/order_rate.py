from decimal import Decimal

from risk_service.domain.checks.base import CheckContext, risk_check
from risk_service.domain.models import CheckResult

NAME = "order_rate"


@risk_check(NAME)
def order_rate(ctx: CheckContext) -> CheckResult:
    limit = ctx.limits.max_orders_per_second
    count = ctx.orders_in_window
    if count <= limit:
        return CheckResult.passed(NAME, limit=Decimal(limit), value=Decimal(count))
    return CheckResult.failed(
        NAME,
        f"{count} orders in the last second exceeds the limit of {limit}",
        limit=Decimal(limit),
        value=Decimal(count),
    )
