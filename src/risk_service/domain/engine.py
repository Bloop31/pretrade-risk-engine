"""Runs every risk check against an order and combines the results."""

from collections.abc import Sequence

from risk_service.domain.checks import DEFAULT_CHECKS, CheckContext, RiskCheck
from risk_service.domain.models import CheckResult, RiskDecision
from risk_service.observability.logging import get_logger

log = get_logger(__name__)


class RiskEngine:
    def __init__(self, checks: Sequence[RiskCheck] = DEFAULT_CHECKS) -> None:
        names = [check.name for check in checks]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate check names: {names}")
        self._checks = tuple(checks)

    @property
    def check_names(self) -> tuple[str, ...]:
        return tuple(check.name for check in self._checks)

    def evaluate(self, ctx: CheckContext, *, rules_version: str) -> RiskDecision:
        """Run every check (no short-circuit) so the caller sees all reasons at once."""
        results = tuple(self._run(check, ctx) for check in self._checks)
        return RiskDecision.from_checks(ctx.order, results, rules_version)

    @staticmethod
    def _run(check: RiskCheck, ctx: CheckContext) -> CheckResult:
        try:
            return check(ctx)
        except Exception:
            # A broken check must never let an order through.
            log.exception(
                "risk_check.error", check=check.name, client_order_id=ctx.order.client_order_id
            )
            return CheckResult.failed(check.name, "internal error while evaluating check")
