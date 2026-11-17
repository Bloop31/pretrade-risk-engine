"""What a risk check is, and the inputs every check receives."""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from risk_service.domain.limits import EffectiveLimits
from risk_service.domain.models import CheckResult, Order, OrderType


@dataclass(frozen=True, slots=True)
class CheckContext:
    """Everything a check may look at. Checks are pure functions of this snapshot."""

    order: Order
    limits: EffectiveLimits
    reference_price: Decimal | None
    """Last known price for the order's symbol, or ``None`` if there is none."""
    position: Decimal
    """Account's signed position in the symbol (long > 0, short < 0), counting open
    orders on the same side as this one: the worst case in the order's direction."""
    gross_exposure: Decimal | None
    """Account's worst-case gross exposure across all symbols, or ``None`` if it
    cannot be valued (a held symbol has no reference price)."""
    orders_in_window: int
    """Orders the account sent in the current rate window, including this one."""

    @property
    def valuation_price(self) -> Decimal | None:
        """Price used to value this order: the limit price, else the reference price."""
        if self.order.order_type is OrderType.LIMIT:
            return self.order.price
        return self.reference_price


@dataclass(frozen=True, slots=True)
class RiskCheck:
    name: str
    evaluate: Callable[[CheckContext], CheckResult]

    def __call__(self, ctx: CheckContext) -> CheckResult:
        return self.evaluate(ctx)


def risk_check(name: str) -> Callable[[Callable[[CheckContext], CheckResult]], RiskCheck]:
    def wrap(fn: Callable[[CheckContext], CheckResult]) -> RiskCheck:
        return RiskCheck(name=name, evaluate=fn)

    return wrap
