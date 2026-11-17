"""FastAPI dependencies that expose objects created in the app lifespan."""

from typing import Annotated, cast

from fastapi import Depends, Request
from redis.asyncio import Redis

from risk_service.settings import Settings


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_redis(request: Request) -> Redis:
    return cast(Redis, request.app.state.redis)


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RedisDep = Annotated[Redis, Depends(get_redis)]
