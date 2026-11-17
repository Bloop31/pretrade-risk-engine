"""A validated, immutable rules snapshot and limit resolution."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from risk_service.domain.limits import EffectiveLimits
from risk_service.rules.schema import LIMIT_FIELDS, RulesDocument


@dataclass(frozen=True, slots=True)
class RuleSet:
    document: RulesDocument
    version: str  # content hash: identical files always get the same version
    source: str
    loaded_at: datetime

    def limits_for(self, account: str, symbol: str) -> EffectiveLimits:
        """Resolve the limits for one order.

        Layers, least to most specific (later wins)::

            defaults  <  symbols[symbol]  <  accounts[account]  <  accounts[account].symbols[symbol]
        """
        doc = self.document
        account_rules = doc.accounts.get(account)

        merged: dict[str, Any] = doc.defaults.model_dump()
        layers = (
            doc.symbols.get(symbol),
            account_rules,
            account_rules.symbols.get(symbol) if account_rules else None,
        )
        for layer in layers:
            if layer is not None:
                merged.update(layer.model_dump(include=set(LIMIT_FIELDS), exclude_none=True))

        halted_by: Literal["global", "account"] | None = None
        if not doc.trading_enabled:
            halted_by = "global"
        elif account_rules is not None and not account_rules.trading_enabled:
            halted_by = "account"

        restricted = symbol in doc.restricted_symbols or (
            account_rules is not None and symbol in account_rules.restricted_symbols
        )
        return EffectiveLimits(**merged, symbol_restricted=restricted, trading_halted_by=halted_by)
