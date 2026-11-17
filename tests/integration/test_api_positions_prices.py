from datetime import UTC, datetime, timedelta

import pytest
from fakeredis import FakeServer
from httpx import AsyncClient


async def test_price_round_trip_normalises_symbol(client: AsyncClient) -> None:
    before = datetime.now(UTC)
    put = await client.put("/v1/prices/aapl", json={"price": "187.123456789"})
    assert put.status_code == 200
    body = put.json()
    assert body["symbol"] == "AAPL"
    assert body["price"] == "187.123456789"
    updated_at = datetime.fromisoformat(body["updated_at"])
    assert before - timedelta(seconds=1) <= updated_at <= datetime.now(UTC) + timedelta(seconds=1)

    get = await client.get("/v1/prices/AAPL")
    assert get.json() == body


async def test_list_prices_sorted(client: AsyncClient) -> None:
    await client.put("/v1/prices/MSFT", json={"price": "400"})
    await client.put("/v1/prices/AAPL", json={"price": "100"})
    assert [p["symbol"] for p in (await client.get("/v1/prices")).json()] == ["AAPL", "MSFT"]


async def test_missing_price_is_404(client: AsyncClient) -> None:
    assert (await client.get("/v1/prices/NOPE")).status_code == 404


@pytest.mark.parametrize("price", ["0", "-5", 1.5, "NaN", "abc"])
async def test_invalid_price_is_422(client: AsyncClient, price: object) -> None:
    response = await client.put("/v1/prices/AAPL", json={"price": price})
    assert response.status_code == 422


async def test_invalid_symbol_in_path_is_422(client: AsyncClient) -> None:
    response = await client.put("/v1/prices/-BAD", json={"price": "1"})
    assert response.status_code == 422


async def test_empty_account(client: AsyncClient) -> None:
    response = await client.get("/v1/positions/ACC-1")
    assert response.json() == {
        "account": "ACC-1",
        "positions": {},
        "open_buys": {},
        "open_sells": {},
        "gross_exposure": "0",
    }


async def test_set_position_and_exposure(client: AsyncClient) -> None:
    await client.put("/v1/prices/AAPL", json={"price": "10.5"})
    put = await client.put("/v1/positions/ACC-1/aapl", json={"quantity": "-200"})
    assert put.json() == {"account": "ACC-1", "symbol": "AAPL", "quantity": "-200"}

    positions = (await client.get("/v1/positions/ACC-1")).json()
    assert positions["positions"] == {"AAPL": "-200"}
    assert positions["gross_exposure"] == "2100.0"


async def test_exposure_is_null_when_a_holding_is_unpriced(client: AsyncClient) -> None:
    await client.put("/v1/positions/ACC-1/MSFT", json={"quantity": "1"})
    assert (await client.get("/v1/positions/ACC-1")).json()["gross_exposure"] is None


async def test_invalid_account_is_422(client: AsyncClient) -> None:
    assert (await client.get("/v1/positions/bad%20account")).status_code == 422


async def test_redis_outage_is_503(client: AsyncClient, redis_server: FakeServer) -> None:
    redis_server.connected = False
    response = await client.get("/v1/positions/ACC-1")
    assert response.status_code == 503
    assert response.json()["error"] == "state_unavailable"
