import asyncio
from pathlib import Path
from typing import Any

import pytest

from risk_service.rules.store import ReloadResult, RulesStore
from risk_service.rules.watcher import RulesWatcher
from tests.conftest import TEST_RULES


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _delete(path: Path) -> None:
    path.unlink()


class CountingStore(RulesStore):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.reloads = 0
        self.swapped = asyncio.Event()

    async def reload(self, **kwargs: Any) -> ReloadResult:
        self.reloads += 1
        result = await super().reload(**kwargs)
        if result.changed:
            self.swapped.set()
        return result


@pytest.fixture
async def store(rules_path: Path) -> CountingStore:
    opened = await RulesStore.open(rules_path)
    return CountingStore(rules_path, opened.current())


@pytest.fixture
def watcher(store: CountingStore) -> RulesWatcher:
    return RulesWatcher(store, interval_seconds=0.01)


async def _settle(watcher: RulesWatcher) -> None:
    await watcher.poll_once()  # sees the change
    await watcher.poll_once()  # confirms it is stable, then reloads


async def test_first_settled_poll_reloads_once_then_idles(
    watcher: RulesWatcher, store: CountingStore
) -> None:
    await _settle(watcher)
    assert store.reloads == 1
    for _ in range(3):
        await watcher.poll_once()
    assert store.reloads == 1


async def test_change_is_applied_after_it_settles(
    watcher: RulesWatcher, store: CountingStore, rules_path: Path
) -> None:
    await _settle(watcher)
    old_version = store.current().version

    _write(rules_path, TEST_RULES.replace("max_position: 5000", "max_position: 12345"))
    await watcher.poll_once()
    assert store.current().version == old_version  # not yet: still settling

    await watcher.poll_once()
    assert store.current().version != old_version
    assert store.current().document.defaults.max_position == 12345


async def test_file_still_changing_is_not_read(
    watcher: RulesWatcher, store: CountingStore, rules_path: Path
) -> None:
    await _settle(watcher)
    for i in range(3):
        _write(rules_path, TEST_RULES + "#" * (i + 1) + "\n")
        await watcher.poll_once()
    assert store.reloads == 1  # every poll saw a different file


async def test_broken_file_is_attempted_once_and_fixed_file_applies(
    watcher: RulesWatcher, store: CountingStore, rules_path: Path
) -> None:
    await _settle(watcher)
    active = store.current()

    _write(rules_path, "schema_version: 1\n")
    await _settle(watcher)
    assert store.reloads == 2
    assert store.current() is active
    assert store.last_error is not None

    await watcher.poll_once()
    await watcher.poll_once()
    assert store.reloads == 2  # same broken file: not retried, not re-logged

    _write(rules_path, TEST_RULES.replace("max_position: 5000", "max_position: 1"))
    await _settle(watcher)
    assert store.reloads == 3
    assert store.last_error is None
    assert store.current().document.defaults.max_position == 1


async def test_missing_file_keeps_current_rules(
    watcher: RulesWatcher, store: CountingStore, rules_path: Path
) -> None:
    await _settle(watcher)
    active = store.current()
    _delete(rules_path)

    await _settle(watcher)
    assert store.current() is active
    assert store.reloads == 1

    _write(rules_path, TEST_RULES.replace("max_position: 5000", "max_position: 2"))
    await _settle(watcher)
    assert store.current().document.defaults.max_position == 2


async def test_background_task_picks_up_edits(store: CountingStore, rules_path: Path) -> None:
    watcher = RulesWatcher(store, interval_seconds=0.02)
    watcher.start()
    try:
        _write(rules_path, TEST_RULES.replace("max_position: 5000", "max_position: 777"))
        await asyncio.wait_for(store.swapped.wait(), timeout=3)
    finally:
        await watcher.stop()
    assert store.current().document.defaults.max_position == 777


async def test_stop_is_idempotent(watcher: RulesWatcher) -> None:
    await watcher.stop()
    watcher.start()
    await watcher.stop()
    await watcher.stop()


def test_interval_must_be_positive(store: CountingStore) -> None:
    with pytest.raises(ValueError, match="positive"):
        RulesWatcher(store, interval_seconds=0)
