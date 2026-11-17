"""Application factory and lifespan.

Run with::

    uvicorn risk_service.main:create_app --factory
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from risk_service import __version__
from risk_service.api import health
from risk_service.observability.logging import configure_logging, get_logger
from risk_service.observability.middleware import ObservabilityMiddleware
from risk_service.settings import Settings, get_settings

log = get_logger(__name__)


def create_redis(settings: Settings) -> Redis:
    return Redis.from_url(
        str(settings.redis_url),
        decode_responses=True,
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=settings.redis_socket_timeout_seconds,
        health_check_interval=30,
    )


def create_app(settings: Settings | None = None, *, redis_client: Redis | None = None) -> FastAPI:
    """Build the FastAPI app.

    ``redis_client`` lets tests inject a fake; when omitted the app owns a
    connection pool built from ``settings.redis_url`` and closes it on shutdown.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = redis_client if redis_client is not None else create_redis(settings)
        app.state.redis = client
        log.info("startup", version=__version__, redis_url=_redact(str(settings.redis_url)))
        try:
            yield
        finally:
            if redis_client is None:
                await client.aclose()
            log.info("shutdown")

    app = FastAPI(
        title="Pre-Trade Risk Check Service",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(ObservabilityMiddleware)
    app.include_router(health.router)
    return app


def _redact(url: str) -> str:
    """Hide the password in a ``redis://user:password@host`` URL before logging it."""
    scheme, sep, rest = url.partition("://")
    creds, at, host = rest.rpartition("@")
    if not at:
        return url
    user = creds.partition(":")[0]
    return f"{scheme}{sep}{user}:***@{host}"
