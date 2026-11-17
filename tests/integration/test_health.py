from collections.abc import AsyncIterator
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from risk_service.main import create_app
from risk_service.settings import Settings


class _DownRedis(FakeAsyncRedis):
    async def ping(self, **kwargs: Any) -> bool:
        raise RedisConnectionError("connection refused")


@pytest.fixture
async def client_redis_down(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings, redis_client=_DownRedis())
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http,
    ):
        yield http


async def test_live(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_when_redis_up(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"redis": True}}


async def test_not_ready_when_redis_down(client_redis_down: AsyncClient) -> None:
    response = await client_redis_down.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": {"redis": False}}


async def test_live_ignores_redis(client_redis_down: AsyncClient) -> None:
    response = await client_redis_down.get("/health/live")
    assert response.status_code == 200


async def test_request_id_is_generated(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert len(response.headers["x-request-id"]) == 32


async def test_valid_request_id_is_echoed(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={"x-request-id": "ord-123:abc"})
    assert response.headers["x-request-id"] == "ord-123:abc"


async def test_unsafe_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={"x-request-id": "bad id\twith spaces"})
    assert response.headers["x-request-id"] != "bad id\twith spaces"
    assert len(response.headers["x-request-id"]) == 32


async def test_metrics_uses_route_template(client: AsyncClient) -> None:
    await client.get("/health/live")
    await client.get("/no/such/path")

    response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert 'risk_http_requests_total{method="GET",route="/health/live",status="200"}' in body
    assert 'route="unmatched",status="404"' in body
    assert "risk_http_request_duration_seconds_bucket" in body
