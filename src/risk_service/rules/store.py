"""Holds the active rule set and swaps it atomically on reload.

A reload only ever replaces a valid rule set with another valid one. If the
file on disk is broken, ``reload`` raises and the previous rules stay active.
Readers call ``current()`` once per order and use that snapshot throughout, so
an order is never evaluated against a mix of old and new rules.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from risk_service.rules.loader import load_rules
from risk_service.rules.ruleset import RuleSet


@dataclass(frozen=True, slots=True)
class ReloadResult:
    changed: bool
    version: str
    previous_version: str


class RulesStore:
    def __init__(self, path: Path, initial: RuleSet) -> None:
        self._path = path
        self._current = initial
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, path: Path) -> "RulesStore":
        """Load the initial rules; raises ``RulesError`` if the file is missing or invalid."""
        return cls(path, await asyncio.to_thread(load_rules, path))

    @property
    def path(self) -> Path:
        return self._path

    def current(self) -> RuleSet:
        return self._current

    async def reload(self) -> ReloadResult:
        """Re-read the file; swap it in if valid. Raises ``RulesError`` otherwise."""
        async with self._lock:
            previous = self._current
            candidate = await asyncio.to_thread(load_rules, self._path)
            changed = candidate.version != previous.version
            if changed:
                self._current = candidate
            return ReloadResult(
                changed=changed, version=self._current.version, previous_version=previous.version
            )
