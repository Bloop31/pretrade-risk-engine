from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fakeredis import FakeAsyncRedis, FakeServer
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from risk_service.main import create_app
from risk_service.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        rules_path=tmp_path / "rules.yaml",
        log_json=False,
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
