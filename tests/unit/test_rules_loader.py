from decimal import Decimal
from pathlib import Path
from textwrap import dedent

import pytest

from risk_service.rules.loader import RulesError, load_rules, parse_rules
from risk_service.rules.ruleset import RuleSet

REPO_RULES = Path(__file__).parents[2] / "config" / "rules.yaml"

MINIMAL = """\
schema_version: 1
defaults:
  max_order_quantity: 1000
  max_order_notional: 100000
  price_collar_pct: 5
  max_position: 5000
  max_gross_exposure: 1000000
  max_orders_per_second: 10
"""


def _parse(extra: str = "", base: str = MINIMAL) -> RuleSet:
    return parse_rules((base + dedent(extra)).encode())


def _problems(text: str) -> list[str]:
    with pytest.raises(RulesError) as exc_info:
        parse_rules(dedent(text).encode())
    return exc_info.value.problems


def test_shipped_rules_file_is_valid() -> None:
    rules = load_rules(REPO_RULES)
    assert rules.document.defaults.max_order_quantity == Decimal(10000)
    assert "XYZ" in rules.document.restricted_symbols
    assert rules.source == str(REPO_RULES)


def test_decimals_are_exact() -> None:
    rules = parse_rules(MINIMAL.replace("price_collar_pct: 5", "price_collar_pct: 0.1").encode())
    collar = rules.document.defaults.price_collar_pct
    assert collar == Decimal("0.1")
    assert str(collar) == "0.1"


def test_underscored_numbers() -> None:
    text = MINIMAL.replace("max_gross_exposure: 1000000", "max_gross_exposure: 1_000_000.50")
    assert parse_rules(text.encode()).document.defaults.max_gross_exposure == Decimal("1000000.50")


@pytest.mark.parametrize("value", [".inf", "-.inf", ".nan"])
def test_non_finite_numbers_are_rejected(value: str) -> None:
    problems = _problems(MINIMAL.replace("price_collar_pct: 5", f"price_collar_pct: {value}"))
    assert "not a valid finite number" in problems[0]


def test_yes_no_on_off_tickers_stay_strings() -> None:
    rules = _parse("restricted_symbols: [NO, ON, Y]\n")
    assert rules.document.restricted_symbols == frozenset({"NO", "ON", "Y"})


def test_numeric_ticker_keys_become_strings() -> None:
    rules = _parse("symbols:\n  7203:\n    max_order_quantity: 10\n")
    assert "7203" in rules.document.symbols


def test_duplicate_keys_are_rejected() -> None:
    problems = _problems(MINIMAL + "symbols:\n  AAPL: {}\n  AAPL: {}\n")
    assert "duplicate key 'AAPL'" in problems[0]


def test_case_insensitive_duplicate_symbols_are_rejected() -> None:
    problems = _problems(MINIMAL + "symbols:\n  aapl: {}\n  AAPL: {}\n")
    assert "same symbol" in problems[0]


def test_misspelt_field_reports_its_path() -> None:
    problems = _problems(MINIMAL + "symbols:\n  AAPL:\n    max_order_qty: 5\n")
    assert problems == ["symbols.AAPL.max_order_qty: Extra inputs are not permitted"]


def test_account_only_limit_is_not_allowed_on_a_symbol() -> None:
    problems = _problems(MINIMAL + "symbols:\n  AAPL:\n    max_gross_exposure: 5\n")
    assert problems[0].startswith("symbols.AAPL.max_gross_exposure")


def test_every_default_is_required() -> None:
    problems = _problems(MINIMAL.replace("  max_position: 5000\n", ""))
    assert problems == ["defaults.max_position: Field required"]


def test_all_problems_are_reported_together() -> None:
    text = MINIMAL.replace("max_order_quantity: 1000", "max_order_quantity: -1").replace(
        "price_collar_pct: 5", "price_collar_pct: 101"
    )
    problems = _problems(text)
    assert len(problems) == 2
    assert problems[0].startswith("defaults.max_order_quantity: Input should be greater than 0")
    assert problems[1].startswith("defaults.price_collar_pct: Input should be less than or equal")


def test_unknown_schema_version() -> None:
    problems = _problems(MINIMAL.replace("schema_version: 1", "schema_version: 2"))
    assert problems[0].startswith("schema_version:")


@pytest.mark.parametrize("text", ["", "- a list\n", "just a string\n"])
def test_top_level_must_be_a_mapping(text: str) -> None:
    assert _problems(text) == ["the file must contain a mapping at the top level"]


def test_yaml_syntax_error() -> None:
    problems = _problems("defaults: [unclosed\n")
    assert problems[0].startswith("YAML syntax error")


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RulesError, match="cannot read file"):
        load_rules(tmp_path / "nope.yaml")


def test_version_is_a_content_hash() -> None:
    a = parse_rules(MINIMAL.encode())
    b = parse_rules(MINIMAL.encode())
    c = parse_rules((MINIMAL + "trading_enabled: false\n").encode())
    assert a.version == b.version
    assert a.version != c.version
    assert len(a.version) == 12
