from decimal import Decimal

import pytest

from risk_service.domain.checks import DEFAULT_CHECKS, CheckContext, risk_check
from risk_service.domain.engine import RiskEngine
from risk_service.domain.models import CheckResult, CheckStatus, Decision
from tests.factories import make_ctx, make_order


@pytest.fixture
def engine() -> RiskEngine:
    return RiskEngine()


def test_clean_order_is_accepted_with_every_check_reported(engine: RiskEngine) -> None:
    decision = engine.evaluate(make_ctx(), rules_version="abc")
    assert decision.decision is Decision.ACCEPT
    assert [c.check for c in decision.checks] == [c.name for c in DEFAULT_CHECKS]
    assert decision.rules_version == "abc"
    assert decision.client_order_id == "ord-1"


def test_all_failures_are_reported_not_just_the_first(engine: RiskEngine) -> None:
    ctx = make_ctx(
        make_order(quantity=Decimal(2000), price=Decimal(200)),
        symbol_restricted=True,
        orders_in_window=99,
    )
    decision = engine.evaluate(ctx, rules_version="abc")
    assert decision.decision is Decision.REJECT
    assert {c.check for c in decision.failed_checks} == {
        "restricted_symbol",
        "order_rate",
        "max_order_quantity",
        "max_order_notional",
        "price_collar",
    }
    assert len(decision.checks) == len(DEFAULT_CHECKS)


def test_a_crashing_check_fails_closed() -> None:
    @risk_check("boom")
    def boom(ctx: CheckContext) -> CheckResult:
        raise RuntimeError("bug")

    @risk_check("ok")
    def ok(ctx: CheckContext) -> CheckResult:
        return CheckResult.passed("ok")

    decision = RiskEngine([ok, boom]).evaluate(make_ctx(), rules_version="v")

    assert decision.decision is Decision.REJECT
    assert decision.checks[1].status is CheckStatus.FAIL
    assert decision.checks[1].reason == "internal error while evaluating check"


def test_duplicate_check_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        RiskEngine([DEFAULT_CHECKS[0], DEFAULT_CHECKS[0]])


def test_engine_with_no_checks_rejects() -> None:
    assert RiskEngine([]).evaluate(make_ctx(), rules_version="v").decision is Decision.REJECT
