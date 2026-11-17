from risk_service.domain.checks.base import CheckContext, risk_check
from risk_service.domain.models import CheckResult

NAME = "max_gross_exposure"


@risk_check(NAME)
def max_gross_exposure(ctx: CheckContext) -> CheckResult:
    """The account's gross exposure after this order fills must stay within the limit.

    The order changes exposure by ``(|position after| - |position before|) x price``,
    using the worst-case position in the order's direction. This can overstate the
    increase when the account also has open orders on the other side, which errs
    on the safe side. As with ``max_position``, an order that reduces exposure is
    always allowed.
    """
    limit = ctx.limits.max_gross_exposure
    price = ctx.valuation_price
    if price is None:
        return CheckResult.failed(
            NAME, f"no reference price for {ctx.order.symbol} to value a MARKET order", limit=limit
        )

    if ctx.gross_exposure is None:
        return CheckResult.failed(
            NAME, "current exposure is unknown: a held symbol has no reference price", limit=limit
        )

    current_position = ctx.position
    new_position = current_position + ctx.order.signed_quantity
    delta = (abs(new_position) - abs(current_position)) * price
    projected = ctx.gross_exposure + delta
    if delta <= 0 or projected <= limit:
        return CheckResult.passed(NAME, limit=limit, value=projected)
    return CheckResult.failed(
        NAME,
        f"gross exposure would be {projected} (currently {ctx.gross_exposure}), "
        f"beyond the limit of {limit}",
        limit=limit,
        value=projected,
    )
