"""An account's positions and open orders, and how they are valued.

Open (accepted but unfilled) orders are tracked per side. Risk is measured
against the worst case: every open buy fills, or every open sell fills,
whichever is further from flat. Opposite-side orders never net against each
other, because there is no guarantee both will fill.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from risk_service.domain.models import Side

_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    positions: Mapping[str, Decimal] = field(default_factory=dict)
    """Filled signed net position per symbol."""
    open_buys: Mapping[str, Decimal] = field(default_factory=dict)
    """Unfilled quantity of accepted BUY orders per symbol (always >= 0)."""
    open_sells: Mapping[str, Decimal] = field(default_factory=dict)
    """Unfilled quantity of accepted SELL orders per symbol (always >= 0)."""

    def position(self, symbol: str) -> Decimal:
        return self.positions.get(symbol, _ZERO)

    def directional_position(self, symbol: str, side: Side) -> Decimal:
        """Worst-case position in the direction an order on ``side`` would move it."""
        if side is Side.BUY:
            return self.position(symbol) + self.open_buys.get(symbol, _ZERO)
        return self.position(symbol) - self.open_sells.get(symbol, _ZERO)

    def worst_case_quantity(self, symbol: str) -> Decimal:
        """Largest absolute position reachable if one whole side of open orders fills."""
        return max(
            abs(self.directional_position(symbol, Side.BUY)),
            abs(self.directional_position(symbol, Side.SELL)),
        )

    def symbols(self) -> frozenset[str]:
        return frozenset(self.positions) | frozenset(self.open_buys) | frozenset(self.open_sells)


def gross_exposure(snapshot: AccountSnapshot, prices: Mapping[str, Decimal]) -> Decimal | None:
    """Sum of worst-case |quantity| x price over every symbol the account touches.

    Returns ``None`` if any symbol with a non-zero exposure has no price: the
    exposure is then unknown and the caller must fail closed.
    """
    total = _ZERO
    for symbol in snapshot.symbols():
        quantity = snapshot.worst_case_quantity(symbol)
        if quantity == 0:
            continue
        price = prices.get(symbol)
        if price is None:
            return None
        total += quantity * price
    return total
