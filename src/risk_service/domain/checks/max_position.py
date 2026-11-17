from risk_service.domain.checks.base import CheckContext, risk_check
from risk_service.domain.models import CheckResult

NAME = "max_position"


@risk_check(NAME)
def max_position(ctx: CheckContext) -> CheckResult:
    """The absolute net position after this order fills must stay within the limit.

    An order that brings the position closer to flat is always allowed, so an
    account that is over its limit (say, after the limit was lowered) can
    still trade out of it.
    """
    limit = ctx.limits.max_position
    current = ctx.position
    projected = current + ctx.order.signed_quantity
    if abs(projected) <= limit or abs(projected) < abs(current):
        return CheckResult.passed(NAME, limit=limit, value=abs(projected))
    return CheckResult.failed(
        NAME,
        f"position would be {projected} (currently {current}), beyond the limit of {limit}",
        limit=limit,
        value=abs(projected),
    )
