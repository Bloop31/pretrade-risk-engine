"""The limits that apply to one (account, symbol) pair after resolving the rules file."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True, slots=True)
class EffectiveLimits:
    max_order_quantity: Decimal
    max_order_notional: Decimal
    price_collar_pct: Decimal
    max_position: Decimal
    max_gross_exposure: Decimal
    max_orders_per_second: int
    max_price_age_seconds: int
    symbol_restricted: bool = False
    trading_halted_by: Literal["global", "account"] | None = None
