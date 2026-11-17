"""The long-lived objects built at startup and shared by every request."""

from dataclasses import dataclass

from redis.asyncio import Redis

from risk_service.domain.engine import RiskEngine
from risk_service.rules.store import RulesStore
from risk_service.services.pretrade import PreTradeService
from risk_service.settings import Settings
from risk_service.state.accounts import AccountStore
from risk_service.state.prices import PriceStore
from risk_service.state.rate import RateLimiter


@dataclass(frozen=True, slots=True)
class Services:
    settings: Settings
    redis: Redis
    rules: RulesStore
    accounts: AccountStore
    prices: PriceStore
    pretrade: PreTradeService

    @classmethod
    def build(cls, settings: Settings, redis: Redis, rules: RulesStore) -> "Services":
        accounts = AccountStore(redis)
        prices = PriceStore(redis)
        pretrade = PreTradeService(
            engine=RiskEngine(),
            rules=rules.current,
            accounts=accounts,
            prices=prices,
            rate_limiter=RateLimiter(redis),
        )
        return cls(
            settings=settings,
            redis=redis,
            rules=rules,
            accounts=accounts,
            prices=prices,
            pretrade=pretrade,
        )
