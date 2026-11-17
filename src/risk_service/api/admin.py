"""Operator endpoints for the rules file. All require the ``X-Admin-Key`` header."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from risk_service.api.deps import SYMBOL_PATTERN_ANY_CASE, RulesDep, require_admin
from risk_service.api.errors import ErrorResponse
from risk_service.api.schemas import (
    EffectiveLimitsResponse,
    RejectedRulesFile,
    ReloadResponse,
    RulesInfoResponse,
)
from risk_service.domain.models import ACCOUNT_PATTERN

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/rules")
async def get_rules(rules: RulesDep) -> RulesInfoResponse:
    """The rule set currently in force.

    ``rejected_file`` is set when the file on disk has been edited but could not
    be loaded: it lists the problems, and the rules shown here remain in force.
    """
    current = rules.current()
    failure = rules.last_error
    return RulesInfoResponse(
        version=current.version,
        source=current.source,
        loaded_at=current.loaded_at,
        document=current.document,
        rejected_file=(
            None
            if failure is None
            else RejectedRulesFile(problems=failure.problems, rejected_at=failure.at)
        ),
    )


@router.post(
    "/rules/reload",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse}},
)
async def reload_rules(rules: RulesDep) -> ReloadResponse:
    """Re-read the rules file now.

    If the file is invalid, returns 422 listing every problem, and the
    previous rules stay in force.
    """
    result = await rules.reload(trigger="admin")
    return ReloadResponse(
        changed=result.changed, version=result.version, previous_version=result.previous_version
    )


@router.get("/rules/limits")
async def effective_limits(
    rules: RulesDep,
    account: Annotated[str, Query(pattern=ACCOUNT_PATTERN)],
    symbol: Annotated[str, Query(pattern=SYMBOL_PATTERN_ANY_CASE)],
) -> EffectiveLimitsResponse:
    """The limits that would apply to an order for this account and symbol."""
    symbol = symbol.upper()
    current = rules.current()
    limits = current.limits_for(account, symbol)
    return EffectiveLimitsResponse(
        account=account, symbol=symbol, rules_version=current.version, **asdict(limits)
    )
