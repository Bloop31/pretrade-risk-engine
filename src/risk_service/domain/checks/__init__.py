"""The risk checks, in the order they are reported.

To add a check: write a module with a ``@risk_check``-decorated function and
append it to ``DEFAULT_CHECKS``.
"""

from risk_service.domain.checks.base import CheckContext, RiskCheck, risk_check
from risk_service.domain.checks.max_gross_exposure import max_gross_exposure
from risk_service.domain.checks.max_order_notional import max_order_notional
from risk_service.domain.checks.max_order_quantity import max_order_quantity
from risk_service.domain.checks.max_position import max_position
from risk_service.domain.checks.order_rate import order_rate
from risk_service.domain.checks.price_collar import price_collar
from risk_service.domain.checks.reference_price_fresh import reference_price_fresh
from risk_service.domain.checks.restricted_symbol import restricted_symbol
from risk_service.domain.checks.trading_enabled import trading_enabled

DEFAULT_CHECKS: tuple[RiskCheck, ...] = (
    trading_enabled,
    restricted_symbol,
    order_rate,
    reference_price_fresh,
    max_order_quantity,
    max_order_notional,
    price_collar,
    max_position,
    max_gross_exposure,
)

__all__ = [
    "DEFAULT_CHECKS",
    "CheckContext",
    "RiskCheck",
    "max_gross_exposure",
    "max_order_notional",
    "max_order_quantity",
    "max_position",
    "order_rate",
    "price_collar",
    "reference_price_fresh",
    "restricted_symbol",
    "risk_check",
    "trading_enabled",
]
