"""Reference prices, normally pushed by a market-data feed.

Each price is timestamped when it is written; the ``reference_price_fresh``
check rejects orders whose reference price is older than
``max_price_age_seconds`` in the rules.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from risk_service.api.deps import PricesDep, SymbolPath, require_api_key
from risk_service.api.errors import ErrorResponse
from risk_service.api.schemas import PriceResponse, SetPriceRequest
from risk_service.state.prices import Quote

router = APIRouter(prefix="/v1/prices", tags=["prices"], dependencies=[Depends(require_api_key)])


def _response(symbol: str, quote: Quote) -> PriceResponse:
    updated_at = None
    if quote.updated_at_ms is not None:
        seconds, millis = divmod(quote.updated_at_ms, 1000)
        updated_at = datetime.fromtimestamp(seconds, UTC) + timedelta(milliseconds=millis)
    return PriceResponse(symbol=symbol, price=quote.price, updated_at=updated_at)


@router.get("")
async def list_prices(prices: PricesDep) -> list[PriceResponse]:
    return [_response(symbol, quote) for symbol, quote in sorted((await prices.all()).items())]


@router.get("/{symbol}", responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}})
async def get_price(symbol: SymbolPath, prices: PricesDep) -> PriceResponse:
    quote = await prices.get(symbol)
    if quote is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no price for {symbol}")
    return _response(symbol, quote)


@router.put("/{symbol}")
async def set_price(symbol: SymbolPath, body: SetPriceRequest, prices: PricesDep) -> PriceResponse:
    return _response(symbol, await prices.set(symbol, body.price))
