"""FastAPI dependencies: lifespan-built services, path parameters, admin auth."""

import secrets
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Path, Request, Security, status
from fastapi.security import APIKeyHeader
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

# ------------------------------------------------------------------------- auth
# Declared as security schemes so /docs shows an "Authorize" button for each.

API_KEY_HEADER = "X-API-Key"
ADMIN_KEY_HEADER = "X-Admin-Key"

_api_key = APIKeyHeader(name=API_KEY_HEADER, scheme_name="ApiKey", auto_error=False)
_admin_key = APIKeyHeader(name=ADMIN_KEY_HEADER, scheme_name="AdminKey", auto_error=False)


def _matches_any(supplied: str, keys: tuple[str, ...]) -> bool:
    # Compare against every key, with no early exit, so timing reveals nothing.
    candidate = supplied.encode()
    matched = False
    for key in keys:
        matched |= secrets.compare_digest(candidate, key.encode())
    return matched


def _unauthorized(header: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        f"missing or invalid {header} header",
        headers={"WWW-Authenticate": "ApiKey"},
    )


def require_api_key(
    settings: SettingsDep, supplied: Annotated[str | None, Security(_api_key)]
) -> None:
    if settings.api_auth_disabled:
        return
    if supplied is None or not _matches_any(supplied, settings.api_key_values):
        raise _unauthorized(API_KEY_HEADER)


def require_admin(
    settings: SettingsDep, supplied: Annotated[str | None, Security(_admin_key)]
) -> None:
    expected = settings.admin_api_key
    if expected is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "admin API is disabled: set ADMIN_API_KEY to enable it"
        )
    if supplied is None or not _matches_any(supplied, (expected.get_secret_value(),)):
        raise _unauthorized(ADMIN_KEY_HEADER)
