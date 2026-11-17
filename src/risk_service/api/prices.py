"""Reference prices, normally pushed by a market-data feed."""

from fastapi import APIRouter, HTTPException, status

from risk_service.api.deps import PricesDep, SymbolPath
from risk_service.api.errors import ErrorResponse
from risk_service.api.schemas import PriceResponse, SetPriceRequest

router = APIRouter(prefix="/v1/prices", tags=["prices"])


@router.get("")
async def list_prices(prices: PricesDep) -> list[PriceResponse]:
    return [
        PriceResponse(symbol=symbol, price=price)
        for symbol, price in sorted((await prices.all()).items())
    ]


@router.get("/{symbol}", responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}})
async def get_price(symbol: SymbolPath, prices: PricesDep) -> PriceResponse:
    price = await prices.get(symbol)
    if price is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no price for {symbol}")
    return PriceResponse(symbol=symbol, price=price)


@router.put("/{symbol}")
async def set_price(symbol: SymbolPath, body: SetPriceRequest, prices: PricesDep) -> PriceResponse:
    await prices.set(symbol, body.price)
    return PriceResponse(symbol=symbol, price=body.price)
