from pathlib import Path

import pytest
from fakeredis import FakeAsyncRedis
from httpx import ASGITransport, AsyncClient

from risk_service.main import create_app
from risk_service.rules.loader import RulesError
from risk_service.settings import Settings
from tests.conftest import API_KEY, TEST_RULES


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


ORDER = {
    "client_order_id": "ord-1",
    "account": "ACC-1",
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "quantity": "800",
    "price": "100",
}


@pytest.mark.parametrize("headers", [{}, {"X-Admin-Key": "wrong"}])
async def test_admin_requires_key(client: AsyncClient, headers: dict[str, str]) -> None:
    response = await client.get("/admin/rules", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "ApiKey"


async def test_admin_disabled_without_configured_key(
    rules_path: Path, redis: FakeAsyncRedis
) -> None:
    settings = Settings(_env_file=None, rules_path=rules_path, log_json=False, api_keys=API_KEY)
    app = create_app(settings, redis_client=redis)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http,
    ):
        response = await http.get("/admin/rules", headers={"X-Admin-Key": "anything"})
    assert response.status_code == 403


async def test_get_rules(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    response = await client.get("/admin/rules", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["version"]) == 12
    assert body["document"]["defaults"]["max_order_quantity"] == "1000"
    assert body["document"]["restricted_symbols"] == ["XYZ"]


async def test_reload_unchanged(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    response = await client.post("/admin/rules/reload", headers=admin_headers)
    body = response.json()
    assert response.status_code == 200
    assert body["changed"] is False
    assert body["version"] == body["previous_version"]


async def test_reload_applies_new_limits(
    client: AsyncClient, admin_headers: dict[str, str], rules_path: Path
) -> None:
    await client.put("/v1/prices/AAPL", json={"price": "100"})
    assert (await client.post("/v1/orders/check", json=ORDER)).json()["decision"] == "ACCEPT"

    _write(rules_path, TEST_RULES.replace("max_order_quantity: 1000", "max_order_quantity: 500"))
    reload = await client.post("/admin/rules/reload", headers=admin_headers)
    assert reload.json()["changed"] is True

    second = (
        await client.post("/v1/orders/check", json={**ORDER, "client_order_id": "ord-2"})
    ).json()
    assert second["decision"] == "REJECT"
    assert second["rules_version"] == reload.json()["version"]


async def test_invalid_reload_keeps_previous_rules(
    client: AsyncClient, admin_headers: dict[str, str], rules_path: Path
) -> None:
    before = (await client.get("/admin/rules", headers=admin_headers)).json()["version"]
    _write(rules_path, TEST_RULES.replace("max_position: 5000", "max_postion: 5000"))

    response = await client.post("/admin/rules/reload", headers=admin_headers)

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "invalid_rules"
    assert "defaults.max_postion: Extra inputs are not permitted" in body["detail"]
    assert "defaults.max_position: Field required" in body["detail"]
    after = (await client.get("/admin/rules", headers=admin_headers)).json()["version"]
    assert after == before


async def test_effective_limits(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    response = await client.get(
        "/admin/rules/limits", params={"account": "ACC-1", "symbol": "xyz"}, headers=admin_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "XYZ"
    assert body["symbol_restricted"] is True
    assert body["max_order_quantity"] == "1000"
    assert body["max_orders_per_second"] == 1000


async def test_startup_fails_on_invalid_rules(tmp_path: Path, redis: FakeAsyncRedis) -> None:
    bad = tmp_path / "bad.yaml"
    _write(bad, "schema_version: 1\n")
    app = create_app(
        Settings(_env_file=None, rules_path=bad, api_auth_disabled=True), redis_client=redis
    )
    with pytest.raises(RulesError, match="defaults"):
        async with app.router.lifespan_context(app):
            pass


async def test_openapi_schema_renders(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/v1/orders/check" in paths
    assert "/admin/rules/reload" in paths
