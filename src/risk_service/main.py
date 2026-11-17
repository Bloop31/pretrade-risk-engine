"""Application factory and lifespan.

Run with::

    uvicorn risk_service.main:create_app --factory
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from risk_service import __version__
from risk_service.api import admin, health, orders, positions, prices
from risk_service.api.errors import install_error_handlers
from risk_service.container import Services
from risk_service.observability.logging import configure_logging, get_logger
from risk_service.observability.middleware import ObservabilityMiddleware
from risk_service.rules.loader import RulesError
from risk_service.rules.store import RulesStore
from risk_service.rules.watcher import RulesWatcher
from risk_service.settings import Settings, get_settings

log = get_logger(__name__)


def create_redis(settings: Settings) -> Redis:
    """Connection pool from ``REDIS_URL``.

    TLS and its options come from the URL itself (``rediss://...?ssl_ca_certs=...``);
    ``REDIS_PASSWORD`` supplies the password when the URL does not carry one.
    """
    password = settings.redis_password
    # redis-py applies options parsed from the URL over these keyword arguments.
    return Redis.from_url(
        str(settings.redis_url),
        password=password.get_secret_value() if password is not None else None,
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
        # Refuse to start without valid rules: there is no safe default.
        try:
            rules = await RulesStore.open(settings.rules_path)
        except RulesError as exc:
            log.critical("startup.invalid_rules", source=exc.source, problems=exc.problems)
            raise

        client = redis_client if redis_client is not None else create_redis(settings)
        app.state.services = Services.build(settings, client, rules)

        watcher = RulesWatcher(rules, interval_seconds=settings.rules_reload_interval_seconds)
        if settings.rules_watch_enabled:
            watcher.start()

        log.info(
            "startup",
            version=__version__,
            rules_version=rules.current().version,
            rules_path=str(settings.rules_path),
            rules_watch=settings.rules_watch_enabled,
            redis_url=_redact(str(settings.redis_url)),
            api_keys=len(settings.api_key_values),
        )
        if settings.api_auth_disabled:
            log.warning("startup.api_auth_disabled", detail="/v1 endpoints accept any caller")
        try:
            yield
        finally:
            await watcher.stop()
            if redis_client is None:
                await client.aclose()
            log.info("shutdown")

    app = FastAPI(
        title="Pre-Trade Risk Check Service",
        version=__version__,
        description=(
            "Checks orders against configurable risk limits before they reach the exchange. "
            "Decimal values are sent and returned as strings."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(ObservabilityMiddleware)
    install_error_handlers(app)
    for module in (orders, positions, prices, admin, health):
        app.include_router(module.router)
    return app


def _redact(url: str) -> str:
    """Hide the password in a ``redis://user:password@host`` URL before logging it."""
    scheme, sep, rest = url.partition("://")
    creds, at, host = rest.rpartition("@")
    if not at:
        return url
    user = creds.partition(":")[0]
    return f"{scheme}{sep}{user}:***@{host}"
