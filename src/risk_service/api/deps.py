"""FastAPI dependencies: lifespan-built services, path parameters, admin auth."""

import secrets
from typing import Annotated, cast

from fastapi import Depends, Header, HTTPException, Path, Request, status
from redis.asyncio import Redis

from risk_service.container import Services
from risk_service.domain.models import ACCOUNT_PATTERN, CLIENT_ORDER_ID_PATTERN
from risk_service.rules.store import RulesStore
from risk_service.services.pretrade import PreTradeService
from risk_service.settings import Settings
from risk_service.state.accounts import AccountStore
from risk_service.state.prices import PriceStore


def get_services(request: Request) -> Services:
    return cast(Services, request.app.state.services)


ServicesDep = Annotated[Services, Depends(get_services)]


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_redis(services: ServicesDep) -> Redis:
    return services.redis


def get_pretrade(services: ServicesDep) -> PreTradeService:
    return services.pretrade


def get_accounts(services: ServicesDep) -> AccountStore:
    return services.accounts


def get_prices(services: ServicesDep) -> PriceStore:
    return services.prices


def get_rules(services: ServicesDep) -> RulesStore:
    return services.rules


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RedisDep = Annotated[Redis, Depends(get_redis)]
PreTradeDep = Annotated[PreTradeService, Depends(get_pretrade)]
AccountsDep = Annotated[AccountStore, Depends(get_accounts)]
PricesDep = Annotated[PriceStore, Depends(get_prices)]
RulesDep = Annotated[RulesStore, Depends(get_rules)]

# ------------------------------------------------------------------ path params

AccountPath = Annotated[str, Path(pattern=ACCOUNT_PATTERN, examples=["ACC-1"])]
ClientOrderIdPath = Annotated[str, Path(pattern=CLIENT_ORDER_ID_PATTERN)]


# Symbols in URLs may be any case (normalised to upper) and cannot contain "/".
SYMBOL_PATTERN_ANY_CASE = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$"


def _symbol(
    symbol: Annotated[str, Path(pattern=SYMBOL_PATTERN_ANY_CASE, examples=["AAPL"])],
) -> str:
    return symbol.upper()


SymbolPath = Annotated[str, Depends(_symbol)]

# ------------------------------------------------------------------ admin auth

ADMIN_KEY_HEADER = "X-Admin-Key"


def require_admin(
    settings: SettingsDep,
    x_admin_key: Annotated[str | None, Header(alias=ADMIN_KEY_HEADER)] = None,
) -> None:
    expected = settings.admin_api_key
    if expected is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "admin API is disabled: set ADMIN_API_KEY to enable it"
        )
    if x_admin_key is None or not secrets.compare_digest(
        x_admin_key.encode(), expected.get_secret_value().encode()
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"missing or invalid {ADMIN_KEY_HEADER} header",
            headers={"WWW-Authenticate": "ApiKey"},
        )
