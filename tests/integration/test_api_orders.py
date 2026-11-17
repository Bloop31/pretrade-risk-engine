from typing import Any

import pytest
from fakeredis import FakeServer
from httpx import AsyncClient

ORDER: dict[str, Any] = {
    "client_order_id": "ord-1",
    "account": "ACC-1",
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "quantity": "100",
    "price": "100.50",
}


@pytest.fixture(autouse=True)
async def _price(client: AsyncClient) -> None:
    response = await client.put("/v1/prices/AAPL", json={"price": "100"})
    assert response.status_code == 200


def _order(**overrides: Any) -> dict[str, Any]:
    return {**ORDER, **overrides}


async def test_accepted_order(client: AsyncClient) -> None:
    response = await client.post("/v1/orders/check", json=ORDER)

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "ACCEPT"
    assert body["client_order_id"] == "ord-1"
    assert len(body["rules_version"]) == 12
    checks = {c["check"]: c for c in body["checks"]}
    assert len(checks) == 9
    assert checks["reference_price_fresh"]["status"] == "PASS"
    assert checks["max_order_notional"] == {
        "check": "max_order_notional",
        "status": "PASS",
        "reason": None,
        "limit": "1000000",
        "value": "10050.00",
    }
    assert checks["price_collar"]["value"] == "0.5000"


async def test_rejected_order_is_still_200_with_reasons(client: AsyncClient) -> None:
    response = await client.post("/v1/orders/check", json=_order(symbol="XYZ", quantity="5000"))

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "REJECT"
    failed = {c["check"]: c["reason"] for c in body["checks"] if c["status"] == "FAIL"}
    assert set(failed) == {"restricted_symbol", "max_order_quantity", "price_collar"}
    assert failed["restricted_symbol"] == "XYZ is on the restricted list"


async def test_rejected_order_reserves_nothing(client: AsyncClient) -> None:
    await client.post("/v1/orders/check", json=_order(quantity="5000"))
    positions = (await client.get("/v1/positions/ACC-1")).json()
    assert positions["open_buys"] == {}


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"price": 100.5}, "must be sent as strings"),
        ({"price": None}, "price is required for LIMIT"),
        ({"order_type": "MARKET"}, "must not be set for MARKET"),
        ({"quantity": "-1"}, "greater than 0"),
        ({"side": "HOLD"}, "BUY"),
        ({"extra": 1}, "Extra inputs"),
    ],
)
async def test_invalid_orders_are_422(
    client: AsyncClient, overrides: dict[str, Any], message: str
) -> None:
    response = await client.post("/v1/orders/check", json=_order(**overrides))
    assert response.status_code == 422
    assert message in response.text


async def test_duplicate_open_order_is_409(client: AsyncClient) -> None:
    await client.post("/v1/orders/check", json=ORDER)
    response = await client.post("/v1/orders/check", json=ORDER)
    assert response.status_code == 409
    assert response.json()["error"] == "duplicate_order"


async def test_order_lifecycle(client: AsyncClient) -> None:
    await client.post("/v1/orders/check", json=_order(quantity="100"))

    open_order = await client.get("/v1/orders/ACC-1/ord-1")
    assert open_order.status_code == 200
    assert open_order.json()["remaining"] == "100"

    fill = await client.post("/v1/orders/ACC-1/ord-1/fills", json={"quantity": "40"})
    assert fill.status_code == 200
    assert fill.json() == {
        "account": "ACC-1",
        "client_order_id": "ord-1",
        "filled": "40",
        "remaining": "60",
    }

    cancel = await client.post("/v1/orders/ACC-1/ord-1/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["released"] == "60"

    positions = (await client.get("/v1/positions/ACC-1")).json()
    assert positions["positions"] == {"AAPL": "40"}
    assert positions["open_buys"] == {}
    assert (await client.get("/v1/orders/ACC-1/ord-1")).status_code == 404


async def test_client_order_id_reusable_after_close(client: AsyncClient) -> None:
    await client.post("/v1/orders/check", json=ORDER)
    await client.post("/v1/orders/ACC-1/ord-1/cancel")
    response = await client.post("/v1/orders/check", json=ORDER)
    assert response.json()["decision"] == "ACCEPT"


async def test_overfill_is_409(client: AsyncClient) -> None:
    await client.post("/v1/orders/check", json=_order(quantity="10"))
    response = await client.post("/v1/orders/ACC-1/ord-1/fills", json={"quantity": "11"})
    assert response.status_code == 409
    assert response.json()["error"] == "overfill"


@pytest.mark.parametrize("path", ["/fills", "/cancel"])
async def test_unknown_order_is_404(client: AsyncClient, path: str) -> None:
    response = await client.post(f"/v1/orders/ACC-1/nope{path}", json={"quantity": "1"})
    assert response.status_code == 404
    assert response.json()["error"] == "unknown_order"


async def test_fill_rejects_float_quantity(client: AsyncClient) -> None:
    await client.post("/v1/orders/check", json=ORDER)
    response = await client.post("/v1/orders/ACC-1/ord-1/fills", json={"quantity": 1.5})
    assert response.status_code == 422


async def test_redis_outage_rejects_order(client: AsyncClient, redis_server: FakeServer) -> None:
    redis_server.connected = False
    response = await client.post("/v1/orders/check", json=ORDER)

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "REJECT"
    assert [c["check"] for c in body["checks"]] == ["risk_state"]
