"""Account positions: inspect, and load start-of-day positions."""

from fastapi import APIRouter

from risk_service.api.deps import AccountPath, AccountsDep, PricesDep, SymbolPath
from risk_service.api.schemas import AccountPositionsResponse, PositionResponse, SetPositionRequest
from risk_service.domain.positions import gross_exposure

router = APIRouter(prefix="/v1/positions", tags=["positions"])


@router.get("/{account}")
async def get_positions(
    account: AccountPath, accounts: AccountsDep, prices: PricesDep
) -> AccountPositionsResponse:
    """Filled positions, open-order reservations and worst-case gross exposure."""
    snapshot = await accounts.snapshot(account)
    current_prices = await prices.get_many(snapshot.symbols())
    return AccountPositionsResponse(
        account=account,
        positions=dict(snapshot.positions),
        open_buys=dict(snapshot.open_buys),
        open_sells=dict(snapshot.open_sells),
        gross_exposure=gross_exposure(snapshot, current_prices),
    )


@router.put("/{account}/{symbol}")
async def set_position(
    account: AccountPath, symbol: SymbolPath, body: SetPositionRequest, accounts: AccountsDep
) -> PositionResponse:
    """Overwrite the filled position, e.g. when loading start-of-day positions.

    Open-order reservations are not touched.
    """
    await accounts.set_position(account, symbol, body.quantity)
    return PositionResponse(account=account, symbol=symbol, quantity=body.quantity)
