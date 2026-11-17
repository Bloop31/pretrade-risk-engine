"""Holds the active rule set and swaps it atomically on reload.

A reload only ever replaces a valid rule set with another valid one. If the
file on disk is broken, ``reload`` raises, the previous rules stay in force,
and the problems are kept in ``last_error`` so operators can see why their
change has not taken effect. Readers call ``current()`` once per order and use
that snapshot throughout, so an order is never evaluated against a mix of old
and new rules.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from risk_service.observability.logging import get_logger
from risk_service.observability.metrics import (
    ReloadTrigger,
    record_rules_loaded,
    record_rules_reload,
)
from risk_service.rules.loader import RulesError, load_rules
from risk_service.rules.ruleset import RuleSet

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReloadResult:
    changed: bool
    version: str
    previous_version: str


@dataclass(frozen=True, slots=True)
class ReloadFailure:
    problems: list[str]
    at: datetime


class RulesStore:
    def __init__(self, path: Path, initial: RuleSet) -> None:
        self._path = path
        self._current = initial
        self._last_error: ReloadFailure | None = None
        self._lock = asyncio.Lock()
        record_rules_loaded(initial.version, initial.source, initial.loaded_at)

    @classmethod
    async def open(cls, path: Path) -> "RulesStore":
        """Load the initial rules; raises ``RulesError`` if the file is missing or invalid."""
        return cls(path, await asyncio.to_thread(load_rules, path))

    @property
    def path(self) -> Path:
        return self._path

    @property
    def last_error(self) -> ReloadFailure | None:
        """Why the file on disk was rejected at the last attempt, if it was."""
        return self._last_error

    def current(self) -> RuleSet:
        return self._current

    async def reload(self, *, trigger: ReloadTrigger) -> ReloadResult:
        """Re-read the file; swap it in if valid. Raises ``RulesError`` otherwise."""
        async with self._lock:
            previous = self._current
            try:
                candidate = await asyncio.to_thread(load_rules, self._path)
            except RulesError as exc:
                self._last_error = ReloadFailure(problems=exc.problems, at=datetime.now(UTC))
                record_rules_reload(trigger, "invalid")
                log.error(
                    "rules.reload_rejected",
                    trigger=trigger,
                    problems=exc.problems,
                    active_version=previous.version,
                )
                raise

            self._last_error = None
            changed = candidate.version != previous.version
            if changed:
                self._current = candidate
                record_rules_loaded(candidate.version, candidate.source, candidate.loaded_at)
            record_rules_reload(trigger, "changed" if changed else "unchanged")
            log.info(
                "rules.reloaded" if changed else "rules.unchanged",
                trigger=trigger,
                version=self._current.version,
                previous_version=previous.version,
            )
            return ReloadResult(
                changed=changed, version=self._current.version, previous_version=previous.version
            )
