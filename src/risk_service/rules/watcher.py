"""Background task that hot-reloads the rules file when it changes on disk.

It polls the file's (mtime, size, inode) rather than using OS file events:
polling behaves the same on every platform, inside containers with bind
mounts, on network shares and in synced folders, where event APIs often miss
or duplicate events.

A change is only acted on once it has *settled*: the file must look the same
on two consecutive polls. That keeps us from reading a half-written file while
an editor is still saving it. Each distinct file state is attempted once, so a
broken file is reported once rather than on every poll.
"""

import asyncio
import contextlib
import os
from pathlib import Path

from risk_service.observability.logging import get_logger
from risk_service.rules.loader import RulesError
from risk_service.rules.store import RulesStore

log = get_logger(__name__)

FileState = tuple[int, int, int]


def _file_state(path: Path) -> FileState:
    st = os.stat(path)
    return (st.st_mtime_ns, st.st_size, st.st_ino)


class RulesWatcher:
    def __init__(self, store: RulesStore, *, interval_seconds: float) -> None:  # float-ok: seconds
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._store = store
        self._interval = interval_seconds
        # None until the first poll: the first settled state triggers one
        # (normally no-op) reload, which covers edits made during startup.
        self._attempted: FileState | None = None
        self._pending: FileState | None = None
        self._unreadable = False
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="rules-watcher")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def poll_once(self) -> None:
        try:
            state = await asyncio.to_thread(_file_state, self._store.path)
        except OSError as exc:
            if not self._unreadable:
                log.error(
                    "rules.file_unreadable",
                    path=str(self._store.path),
                    error=exc.strerror or repr(exc),
                    active_version=self._store.current().version,
                )
                self._unreadable = True
            self._pending = None
            return
        self._unreadable = False

        if state == self._attempted:
            self._pending = None
            return
        if state != self._pending:
            self._pending = state  # changed since last poll: wait for it to settle
            return

        self._attempted, self._pending = state, None
        with contextlib.suppress(RulesError):  # the store has logged and recorded it
            await self._store.reload(trigger="watcher")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.poll_once()
            except Exception:
                # Never let the watcher die: hot reload must keep working.
                log.exception("rules.watcher_error")
