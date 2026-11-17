from decimal import Decimal

import pytest

from risk_service.rules.loader import parse_rules
from risk_service.rules.ruleset import RuleSet

RULES = b"""\
schema_version: 1
defaults:
  max_order_quantity: 1000
  max_order_notional: 100000
  price_collar_pct: 5
  max_position: 5000
  max_gross_exposure: 1000000
  max_orders_per_second: 10
restricted_symbols: [XYZ]
symbols:
  AAPL:
    max_order_quantity: 200
    price_collar_pct: 2
accounts:
  BIG:
    max_order_quantity: 3000
    max_gross_exposure: 9000000
    symbols:
      AAPL:
        max_order_quantity: 4000
  SMALL:
    max_orders_per_second: 2
    restricted_symbols: [GME]
  OFF:
    trading_enabled: false
"""


@pytest.fixture(scope="module")
def rules() -> RuleSet:
    return parse_rules(RULES)


def test_unknown_account_and_symbol_get_defaults(rules: RuleSet) -> None:
    limits = rules.limits_for("NOBODY", "MSFT")
    assert limits.max_order_quantity == Decimal(1000)
    assert limits.max_orders_per_second == 10
    assert not limits.symbol_restricted
    assert limits.trading_halted_by is None


def test_symbol_overrides_defaults(rules: RuleSet) -> None:
    limits = rules.limits_for("NOBODY", "AAPL")
    assert limits.max_order_quantity == Decimal(200)
    assert limits.price_collar_pct == Decimal(2)
    assert limits.max_position == Decimal(5000)  # inherited


def test_account_overrides_symbol(rules: RuleSet) -> None:
    limits = rules.limits_for("BIG", "MSFT")
    assert limits.max_order_quantity == Decimal(3000)
    assert limits.max_gross_exposure == Decimal(9000000)


def test_account_symbol_is_most_specific(rules: RuleSet) -> None:
    limits = rules.limits_for("BIG", "AAPL")
    assert limits.max_order_quantity == Decimal(4000)
    assert limits.price_collar_pct == Decimal(2)  # still from symbols.AAPL
    assert limits.max_gross_exposure == Decimal(9000000)  # from accounts.BIG


def test_restricted_symbols_global_and_per_account(rules: RuleSet) -> None:
    assert rules.limits_for("NOBODY", "XYZ").symbol_restricted
    assert rules.limits_for("SMALL", "XYZ").symbol_restricted
    assert rules.limits_for("SMALL", "GME").symbol_restricted
    assert not rules.limits_for("BIG", "GME").symbol_restricted


def test_account_kill_switch(rules: RuleSet) -> None:
    assert rules.limits_for("OFF", "AAPL").trading_halted_by == "account"
    assert rules.limits_for("BIG", "AAPL").trading_halted_by is None


def test_global_kill_switch_wins() -> None:
    rules = parse_rules(RULES + b"trading_enabled: false\n")
    assert rules.limits_for("BIG", "AAPL").trading_halted_by == "global"
    assert rules.limits_for("OFF", "AAPL").trading_halted_by == "global"
