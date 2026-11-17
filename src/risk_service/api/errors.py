"""Map domain and state exceptions to HTTP responses.

Error bodies share FastAPI's ``{"detail": ...}`` shape, plus a stable
machine-readable ``error`` code.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis.exceptions import RedisError

from risk_service.observability.logging import get_logger
from risk_service.rules.loader import RulesError
from risk_service.state.errors import (
    DuplicateOrderError,
    OverfillError,
    StateError,
    UnknownOrderError,
)

log = get_logger(__name__)


class ErrorResponse(BaseModel):
    error: str
    detail: str | list[str]


_MAPPING: dict[type[Exception], tuple[int, str]] = {
    DuplicateOrderError: (status.HTTP_409_CONFLICT, "duplicate_order"),
    OverfillError: (status.HTTP_409_CONFLICT, "overfill"),
    UnknownOrderError: (status.HTTP_404_NOT_FOUND, "unknown_order"),
    RulesError: (status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_rules"),
    StateError: (status.HTTP_503_SERVICE_UNAVAILABLE, "state_unavailable"),
    RedisError: (status.HTTP_503_SERVICE_UNAVAILABLE, "state_unavailable"),
}


async def _handle(request: Request, exc: Exception) -> JSONResponse:
    status_code, code = next(_MAPPING[cls] for cls in type(exc).__mro__ if cls in _MAPPING)
    detail: str | list[str] = exc.problems if isinstance(exc, RulesError) else str(exc)
    if status_code >= 500:
        log.error("request.failed", error=code, exc_info=exc, path=request.url.path)
    else:
        log.info("request.refused", error=code, detail=detail, path=request.url.path)
    body = ErrorResponse(error=code, detail=detail)
    return JSONResponse(status_code=status_code, content=body.model_dump())


def install_error_handlers(app: FastAPI) -> None:
    for exc_type in _MAPPING:
        app.add_exception_handler(exc_type, _handle)
