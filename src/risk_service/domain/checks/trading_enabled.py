from risk_service.domain.checks.base import CheckContext, risk_check
from risk_service.domain.models import CheckResult

NAME = "trading_enabled"


@risk_check(NAME)
def trading_enabled(ctx: CheckContext) -> CheckResult:
    """Kill switch: rejects everything when trading is halted globally or for the account."""
    match ctx.limits.trading_halted_by:
        case "global":
            return CheckResult.failed(NAME, "trading is halted for all accounts")
        case "account":
            return CheckResult.failed(NAME, f"trading is halted for account {ctx.order.account}")
        case None:
            return CheckResult.passed(NAME)
