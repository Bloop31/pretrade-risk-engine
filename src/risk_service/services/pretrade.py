"""The pre-trade check use case: gather state, run the engine, reserve on ACCEPT."""

from collections.abc import Callable

from redis.exceptions import RedisError

from risk_service.domain.checks import CheckContext
from risk_service.domain.engine import RiskEngine
from risk_service.domain.models import CheckResult, Order, RiskDecision
from risk_service.domain.positions import AccountSnapshot, gross_exposure
from risk_service.observability.logging import get_logger
from risk_service.rules.ruleset import RuleSet
from risk_service.state.accounts import AccountStore
from risk_service.state.errors import StateError
from risk_service.state.prices import PriceStore
from risk_service.state.rate import RateLimiter

log = get_logger(__name__)

STATE_CHECK = "risk_state"


class PreTradeService:
    def __init__(
        self,
        *,
        engine: RiskEngine,
        rules: Callable[[], RuleSet],
        accounts: AccountStore,
        prices: PriceStore,
        rate_limiter: RateLimiter,
    ) -> None:
        self._engine = engine
        self._rules = rules
        self._accounts = accounts
        self._prices = prices
        self._rate_limiter = rate_limiter

    async def check(self, order: Order) -> RiskDecision:
        """Return the decision for ``order``; on ACCEPT its quantity is reserved.

        Fails closed: if risk state cannot be read or written, the order is
        rejected with a ``risk_state`` check failure. Raises
        ``OrderLifecycleError`` for a duplicate ``client_order_id``.
        """
        rules = self._rules()  # one snapshot for the whole check, even across retries
        limits = rules.limits_for(order.account, order.symbol)

        try:
            orders_in_window = await self._rate_limiter.hit(order.account)

            async def decide(snapshot: AccountSnapshot) -> RiskDecision:
                prices = await self._prices.get_many(snapshot.symbols() | {order.symbol})
                ctx = CheckContext(
                    order=order,
                    limits=limits,
                    reference_price=prices.get(order.symbol),
                    position=snapshot.directional_position(order.symbol, order.side),
                    gross_exposure=gross_exposure(snapshot, prices),
                    orders_in_window=orders_in_window,
                )
                return self._engine.evaluate(ctx, rules_version=rules.version)

            decision = await self._accounts.evaluate_and_reserve(order, decide)
        except (RedisError, StateError, OSError, TimeoutError) as exc:
            log.error(
                "pretrade.state_unavailable",
                client_order_id=order.client_order_id,
                account=order.account,
                error=repr(exc),
            )
            failure = CheckResult.failed(
                STATE_CHECK, f"risk state unavailable: {type(exc).__name__}"
            )
            return RiskDecision.from_checks(order, (failure,), rules.version)

        log.info(
            "pretrade.decision",
            client_order_id=order.client_order_id,
            account=order.account,
            symbol=order.symbol,
            decision=decision.decision.value,
            failed=[c.check for c in decision.failed_checks],
            rules_version=rules.version,
        )
        return decision
