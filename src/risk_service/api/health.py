"""Liveness, readiness and Prometheus scrape endpoints."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError

from risk_service.api.deps import RedisDep, SettingsDep
from risk_service.observability.logging import get_logger

router = APIRouter(tags=["health"])
log = get_logger(__name__)


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, bool]


@router.get("/health/live")
async def live() -> LivenessResponse:
    """The process is up and serving HTTP. Says nothing about dependencies."""
    return LivenessResponse()


@router.get(
    "/health/ready",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def ready(redis: RedisDep, settings: SettingsDep, response: Response) -> ReadinessResponse:
    """The service can make risk decisions: every dependency it needs is reachable."""
    checks = {"redis": await _redis_ok(redis, settings.health_check_timeout_seconds)}
    is_ready = all(checks.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ok" if is_ready else "unavailable", checks=checks)


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def _redis_ok(redis: Redis, timeout_seconds: float) -> bool:
    try:
        async with asyncio.timeout(timeout_seconds):
            await redis.ping()
    except (RedisError, OSError, TimeoutError) as exc:
        log.warning("readiness.redis_unavailable", error=repr(exc))
        return False
    return True
