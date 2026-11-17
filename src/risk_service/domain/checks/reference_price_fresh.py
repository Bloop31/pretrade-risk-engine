from decimal import Decimal

from risk_service.domain.checks.base import CheckContext, risk_check
from risk_service.domain.models import CheckResult

NAME = "reference_price_fresh"

_MS_PER_SECOND = Decimal(1000)


@risk_check(NAME)
def reference_price_fresh(ctx: CheckContext) -> CheckResult:
    """The reference price must be recent: a stale price means the feed may be down,
    and every price-based check would be judging the order against an old market.
    """
    limit = Decimal(ctx.limits.max_price_age_seconds)
    symbol = ctx.order.symbol
    if ctx.reference_price is None:
        # The price-based checks reject this order themselves, with a clearer reason.
        return CheckResult.skipped(NAME, f"no reference price for {symbol}")
    if ctx.reference_price_age_ms is None:
        return CheckResult.failed(
            NAME,
            f"reference price for {symbol} has no timestamp, so its age is unknown",
            limit=limit,
        )

    age = Decimal(ctx.reference_price_age_ms) / _MS_PER_SECOND
    if age <= limit:
        return CheckResult.passed(NAME, limit=limit, value=age)
    return CheckResult.failed(
        NAME,
        f"reference price for {symbol} is {age}s old, older than the {limit}s limit",
        limit=limit,
        value=age,
    )
