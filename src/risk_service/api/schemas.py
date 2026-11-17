"""Request and response bodies that are not domain models themselves."""

from datetime import datetime

from risk_service.domain.models import (
    AccountId,
    ClientOrderId,
    DecimalStr,
    DomainModel,
    PositiveDecimal,
    Side,
    Symbol,
)
from risk_service.rules.schema import RulesDocument


class FillRequest(DomainModel):
    quantity: PositiveDecimal


class FillResponse(DomainModel):
    account: AccountId
    client_order_id: ClientOrderId
    filled: DecimalStr
    remaining: DecimalStr


class CancelResponse(DomainModel):
    account: AccountId
    client_order_id: ClientOrderId
    released: DecimalStr


class OpenOrderResponse(DomainModel):
    account: AccountId
    client_order_id: ClientOrderId
    symbol: Symbol
    side: Side
    quantity: DecimalStr
    remaining: DecimalStr


class AccountPositionsResponse(DomainModel):
    account: AccountId
    positions: dict[str, DecimalStr]
    open_buys: dict[str, DecimalStr]
    open_sells: dict[str, DecimalStr]
    gross_exposure: DecimalStr | None
    """Worst-case gross exposure at current prices; null if a held symbol has no price."""


class SetPositionRequest(DomainModel):
    quantity: DecimalStr
    """Signed filled position: positive long, negative short, zero flat."""


class PositionResponse(DomainModel):
    account: AccountId
    symbol: Symbol
    quantity: DecimalStr


class SetPriceRequest(DomainModel):
    price: PositiveDecimal


class PriceResponse(DomainModel):
    symbol: Symbol
    price: DecimalStr


class RulesInfoResponse(DomainModel):
    version: str
    source: str
    loaded_at: datetime
    document: RulesDocument


class ReloadResponse(DomainModel):
    changed: bool
    version: str
    previous_version: str


class EffectiveLimitsResponse(DomainModel):
    account: AccountId
    symbol: Symbol
    rules_version: str
    max_order_quantity: DecimalStr
    max_order_notional: DecimalStr
    price_collar_pct: DecimalStr
    max_position: DecimalStr
    max_gross_exposure: DecimalStr
    max_orders_per_second: int
    symbol_restricted: bool
    trading_halted_by: str | None
