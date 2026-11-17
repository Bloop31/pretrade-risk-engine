import pytest
from fakeredis import FakeAsyncRedis
from httpx import ASGITransport, AsyncClient

from risk_service.main import create_app
from risk_service.settings import Settings
from tests.conftest import ADMIN_KEY, API_KEY

PROTECTED = [
    ("POST", "/v1/orders/check"),
    ("GET", "/v1/orders/ACC-1/ord-1"),
    ("POST", "/v1/orders/ACC-1/ord-1/fills"),
    ("POST", "/v1/orders/ACC-1/ord-1/cancel"),
    ("GET", "/v1/positions/ACC-1"),
    ("PUT", "/v1/positions/ACC-1/AAPL"),
    ("GET", "/v1/prices"),
    ("GET", "/v1/prices/AAPL"),
    ("PUT", "/v1/prices/AAPL"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
@pytest.mark.parametrize("key", [None, "wrong-key-xxxxxxxxxx", ADMIN_KEY])
async def test_v1_requires_a_client_key(
    client: AsyncClient, method: str, path: str, key: str | None
) -> None:
    headers = {"X-API-Key": key} if key else {}
    client.headers.pop("X-API-Key")
    response = await client.request(method, path, headers=headers, json={})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "ApiKey"


@pytest.mark.parametrize("path", ["/health/live", "/health/ready", "/metrics"])
async def test_probes_and_metrics_are_open(client: AsyncClient, path: str) -> None:
    client.headers.pop("X-API-Key")
    assert (await client.get(path)).status_code == 200


async def test_valid_key_is_accepted(client: AsyncClient) -> None:
    assert (await client.get("/v1/prices")).status_code == 200


async def test_client_key_does_not_open_admin(client: AsyncClient) -> None:
    response = await client.get("/admin/rules", headers={"X-Admin-Key": API_KEY})
    assert response.status_code == 401


async def test_every_rotated_key_works(settings: Settings, redis: FakeAsyncRedis) -> None:
    old, new = "old-client-key-000001", "new-client-key-000002"
    rotating = Settings(
        _env_file=None,
        rules_path=settings.rules_path,
        api_keys=f"{old},{new}",
        rules_watch_enabled=False,
    )
    app = create_app(rotating, redis_client=redis)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http,
    ):
        for key in (old, new):
            response = await http.get("/v1/prices", headers={"X-API-Key": key})
            assert response.status_code == 200


async def test_auth_can_be_disabled_for_local_development(
    settings: Settings, redis: FakeAsyncRedis
) -> None:
    open_settings = Settings(
        _env_file=None,
        rules_path=settings.rules_path,
        api_auth_disabled=True,
        rules_watch_enabled=False,
    )
    app = create_app(open_settings, redis_client=redis)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http,
    ):
        assert (await http.get("/v1/prices")).status_code == 200


async def test_openapi_documents_both_schemes(client: AsyncClient) -> None:
    schemes = (await client.get("/openapi.json")).json()["components"]["securitySchemes"]
    assert schemes["ApiKey"] == {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    assert schemes["AdminKey"]["name"] == "X-Admin-Key"
