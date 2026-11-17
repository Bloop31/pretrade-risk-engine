from risk_service.domain.checks.base import CheckContext, risk_check
from risk_service.domain.models import CheckResult

NAME = "restricted_symbol"


@risk_check(NAME)
def restricted_symbol(ctx: CheckContext) -> CheckResult:
    if ctx.limits.symbol_restricted:
        return CheckResult.failed(NAME, f"{ctx.order.symbol} is on the restricted list")
    return CheckResult.passed(NAME)
