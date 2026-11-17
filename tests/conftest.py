from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fakeredis import FakeAsyncRedis, FakeServer
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from risk_service.main import create_app
from risk_service.settings import Settings

ADMIN_KEY = "test-admin-key"

TEST_RULES = """\
schema_version: 1
defaults:
  max_order_quantity: 1000
  max_order_notional: 1000000
  price_collar_pct: 5
  max_position: 5000
  max_gross_exposure: 10000000
  max_orders_per_second: 1000
restricted_symbols: [XYZ]
"""


@pytest.fixture
def rules_path(tmp_path: Path) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(TEST_RULES, encoding="utf-8")
    return path


@pytest.fixture
def settings(rules_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        rules_path=rules_path,
        log_json=False,
        admin_api_key=ADMIN_KEY,
        rules_watch_enabled=False,  # watcher has its own tests; keep the rest deterministic
    )


@pytest.fixture
def redis_server() -> FakeServer:
    return FakeServer()


@pytest.fixture
async def redis(redis_server: FakeServer) -> AsyncIterator[FakeAsyncRedis]:
    client = FakeAsyncRedis(server=redis_server, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
async def other_redis(redis_server: FakeServer) -> AsyncIterator[FakeAsyncRedis]:
    """A second client on the same server, to play a concurrent writer."""
    client = FakeAsyncRedis(server=redis_server, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def app(settings: Settings, redis: FakeAsyncRedis) -> FastAPI:
    return create_app(settings, redis_client=redis)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    # httpx's ASGITransport does not run the lifespan, so drive it explicitly.
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http,
    ):
        yield http


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": ADMIN_KEY}
