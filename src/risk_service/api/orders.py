"""Pre-trade checks and the order lifecycle that releases reserved risk."""

from fastapi import APIRouter, HTTPException, status

from risk_service.api.deps import AccountPath, AccountsDep, ClientOrderIdPath, PreTradeDep
from risk_service.api.errors import ErrorResponse
from risk_service.api.schemas import (
    CancelResponse,
    FillRequest,
    FillResponse,
    OpenOrderResponse,
)
from risk_service.domain.models import Order, RiskDecision

router = APIRouter(prefix="/v1/orders", tags=["orders"])


@router.post(
    "/check",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def check_order(order: Order, service: PreTradeDep) -> RiskDecision:
    """Check an order against every risk limit.

    Returns 200 with ``decision`` ACCEPT or REJECT and one result per check.
    On ACCEPT the order's quantity is reserved against the account's limits
    until it is filled or cancelled. A ``client_order_id`` that is already open
    for the account returns 409.
    """
    return await service.check(order)


@router.get(
    "/{account}/{client_order_id}",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_open_order(
    account: AccountPath, client_order_id: ClientOrderIdPath, accounts: AccountsDep
) -> OpenOrderResponse:
    """An accepted order that is not yet fully filled or cancelled."""
    order = await accounts.get_open_order(account, client_order_id)
    if order is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"no open order {client_order_id} for account {account}"
        )
    return OpenOrderResponse(
        account=account,
        client_order_id=order.client_order_id,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        remaining=order.remaining,
    )


@router.post(
    "/{account}/{client_order_id}/fills",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def fill_order(
    account: AccountPath,
    client_order_id: ClientOrderIdPath,
    fill: FillRequest,
    accounts: AccountsDep,
) -> FillResponse:
    """Record an execution: moves quantity from the reservation into the position."""
    remaining = await accounts.apply_fill(account, client_order_id, fill.quantity)
    return FillResponse(
        account=account,
        client_order_id=client_order_id,
        filled=fill.quantity,
        remaining=remaining,
    )


@router.post(
    "/{account}/{client_order_id}/cancel",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def cancel_order(
    account: AccountPath, client_order_id: ClientOrderIdPath, accounts: AccountsDep
) -> CancelResponse:
    """Cancel (or expire / reject at the exchange): releases the unfilled remainder."""
    released = await accounts.release(account, client_order_id)
    return CancelResponse(account=account, client_order_id=client_order_id, released=released)
