"""Core domain types.

Every price, quantity and notional is a ``Decimal``. On the wire, Decimals are
accepted as strings or integers (never floats, which have already lost
precision by the time we see them) and serialised as plain strings
(``"1000.50"``, never ``"1.0005E+3"``).
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer, model_validator


def _plain_decimal(value: Decimal) -> str:
    return format(value, "f")


def _reject_binary_floats(value: object) -> object:
    # JSON numbers with a fraction reach us as Python floats, already rounded:
    # 0.1000000000000000055 arrives as 0.1. Refuse them rather than guess.
    if isinstance(value, float | bool):  # float-ok: this is the guard
        raise ValueError(
            'decimal values must be sent as strings (e.g. "187.25") or integers, '
            "not floating-point numbers"
        )
    return value


def _normalise_symbol(value: object) -> object:
    # YAML reads a numeric ticker such as 7203 as an int; treat it as text.
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    return value.strip().upper() if isinstance(value, str) else value


DecimalStr = Annotated[
    Decimal,
    BeforeValidator(_reject_binary_floats),
    Field(allow_inf_nan=False),
    PlainSerializer(_plain_decimal, return_type=str, when_used="json"),
]
PositiveDecimal = Annotated[DecimalStr, Field(gt=0)]
NonNegativeDecimal = Annotated[DecimalStr, Field(ge=0)]

SYMBOL_PATTERN = r"^[A-Z0-9][A-Z0-9._/-]{0,31}$"
ACCOUNT_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
CLIENT_ORDER_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"

Symbol = Annotated[
    str,
    BeforeValidator(_normalise_symbol),
    Field(pattern=SYMBOL_PATTERN, examples=["AAPL"]),
]
AccountId = Annotated[str, Field(pattern=ACCOUNT_PATTERN, examples=["ACC-1"])]
ClientOrderId = Annotated[str, Field(pattern=CLIENT_ORDER_ID_PATTERN, examples=["ord-0001"])]


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class CheckStatus(StrEnum):
    PASS = "PASS"  # noqa: S105 - not a password
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"  # the check does not apply to this order (e.g. price collar on MARKET)


class Decision(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class Order(DomainModel):
    client_order_id: ClientOrderId
    account: AccountId
    symbol: Symbol
    side: Side
    order_type: OrderType
    quantity: PositiveDecimal
    price: PositiveDecimal | None = Field(
        default=None, description="Limit price. Required for LIMIT, must be omitted for MARKET."
    )

    @model_validator(mode="after")
    def _price_matches_order_type(self) -> Self:
        if self.order_type is OrderType.LIMIT and self.price is None:
            raise ValueError("price is required for LIMIT orders")
        if self.order_type is OrderType.MARKET and self.price is not None:
            raise ValueError("price must not be set for MARKET orders")
        return self

    @property
    def signed_quantity(self) -> Decimal:
        """Quantity as a position delta: positive for BUY, negative for SELL."""
        return self.quantity if self.side is Side.BUY else -self.quantity


class CheckResult(DomainModel):
    check: str
    status: CheckStatus
    reason: str | None = None
    limit: DecimalStr | None = Field(default=None, description="The configured limit.")
    value: DecimalStr | None = Field(
        default=None, description="The value compared against the limit."
    )

    @classmethod
    def passed(
        cls, check: str, *, limit: Decimal | None = None, value: Decimal | None = None
    ) -> Self:
        return cls(check=check, status=CheckStatus.PASS, limit=limit, value=value)

    @classmethod
    def failed(
        cls,
        check: str,
        reason: str,
        *,
        limit: Decimal | None = None,
        value: Decimal | None = None,
    ) -> Self:
        return cls(check=check, status=CheckStatus.FAIL, reason=reason, limit=limit, value=value)

    @classmethod
    def skipped(cls, check: str, reason: str) -> Self:
        return cls(check=check, status=CheckStatus.SKIPPED, reason=reason)


class RiskDecision(DomainModel):
    client_order_id: ClientOrderId
    account: AccountId
    symbol: Symbol
    decision: Decision
    rules_version: str
    checks: tuple[CheckResult, ...]

    @model_validator(mode="after")
    def _decision_matches_checks(self) -> Self:
        if self.decision is not _decide(self.checks):
            raise ValueError("decision is inconsistent with check results")
        return self

    @classmethod
    def from_checks(cls, order: Order, checks: tuple[CheckResult, ...], rules_version: str) -> Self:
        return cls(
            client_order_id=order.client_order_id,
            account=order.account,
            symbol=order.symbol,
            decision=_decide(checks),
            rules_version=rules_version,
            checks=checks,
        )

    @property
    def failed_checks(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if c.status is CheckStatus.FAIL)


def _decide(checks: tuple[CheckResult, ...]) -> Decision:
    # An order with no checks at all is not provably safe: fail closed.
    if not checks or any(c.status is CheckStatus.FAIL for c in checks):
        return Decision.REJECT
    return Decision.ACCEPT
