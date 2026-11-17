"""Schema of the business-editable rules file (``config/rules.yaml``).

Every model forbids unknown keys, so a misspelt limit fails validation instead
of being silently ignored. See ``docs/RULES.md`` for the user-facing guide.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator

from risk_service.domain.models import (
    AccountId,
    DecimalStr,
    NonNegativeDecimal,
    PositiveDecimal,
    Symbol,
)

CollarPct = Annotated[DecimalStr, Field(gt=0, le=100)]


def _reject_symbol_collisions(value: object) -> object:
    """``aapl`` and ``AAPL`` both normalise to ``AAPL``; refuse to silently keep one."""
    if isinstance(value, dict):
        seen: dict[str, object] = {}
        for key in value:
            normalised = str(key).strip().upper()
            if normalised in seen:
                raise ValueError(f"{seen[normalised]!r} and {key!r} are the same symbol")
            seen[normalised] = key
    return value


class _RulesModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SymbolLimits(_RulesModel):
    """Limits that may vary per symbol. Omitted fields inherit from the level above."""

    max_order_quantity: PositiveDecimal | None = None
    max_order_notional: PositiveDecimal | None = None
    price_collar_pct: CollarPct | None = None
    max_position: NonNegativeDecimal | None = None


class AccountLimits(SymbolLimits):
    """Symbol-level limits plus the limits that only make sense per account."""

    max_gross_exposure: NonNegativeDecimal | None = None
    max_orders_per_second: PositiveInt | None = None


class Defaults(_RulesModel):
    """Firm-wide limits. All are required, so nothing is ever unlimited by omission."""

    max_order_quantity: PositiveDecimal
    max_order_notional: PositiveDecimal
    price_collar_pct: CollarPct
    max_position: NonNegativeDecimal
    max_gross_exposure: NonNegativeDecimal
    max_orders_per_second: PositiveInt


LIMIT_FIELDS: frozenset[str] = frozenset(Defaults.model_fields)


class AccountRules(AccountLimits):
    trading_enabled: bool = True
    restricted_symbols: frozenset[Symbol] = frozenset()
    symbols: dict[Symbol, SymbolLimits] = Field(default_factory=dict)

    @field_validator("symbols", mode="before")
    @classmethod
    def _unique_symbols(cls, value: object) -> object:
        return _reject_symbol_collisions(value)


class RulesDocument(_RulesModel):
    schema_version: Literal[1]
    trading_enabled: bool = Field(default=True, description="Global kill switch.")
    defaults: Defaults
    restricted_symbols: frozenset[Symbol] = frozenset()
    symbols: dict[Symbol, SymbolLimits] = Field(default_factory=dict)
    accounts: dict[AccountId, AccountRules] = Field(default_factory=dict)

    @field_validator("symbols", mode="before")
    @classmethod
    def _unique_symbols(cls, value: object) -> object:
        return _reject_symbol_collisions(value)
