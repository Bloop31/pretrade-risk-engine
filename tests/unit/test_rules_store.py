from pathlib import Path

import pytest

from risk_service.rules.loader import RulesError
from risk_service.rules.store import RulesStore
from tests.conftest import TEST_RULES
from tests.metrics import sample


@pytest.fixture
async def store(rules_path: Path) -> RulesStore:
    return await RulesStore.open(rules_path)


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


async def test_open_publishes_rules_info(store: RulesStore) -> None:
    version = store.current().version
    assert sample("risk_rules_info", version=version, source=str(store.path)) == 1
    assert sample("risk_rules_file_valid") == 1


async def test_open_fails_on_invalid_file(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    _write(path, "schema_version: 1\n")
    with pytest.raises(RulesError):
        await RulesStore.open(path)


async def test_reload_unchanged(store: RulesStore) -> None:
    before = sample("risk_rules_reloads_total", trigger="admin", result="unchanged")
    result = await store.reload(trigger="admin")
    assert not result.changed
    assert sample("risk_rules_reloads_total", trigger="admin", result="unchanged") == before + 1


async def test_reload_changed_swaps_rules(store: RulesStore, rules_path: Path) -> None:
    old = store.current()
    _write(rules_path, TEST_RULES.replace("max_position: 5000", "max_position: 10"))

    result = await store.reload(trigger="watcher")

    assert result.changed
    assert result.previous_version == old.version
    assert store.current().version == result.version != old.version
    assert store.current().document.defaults.max_position == 10


async def test_invalid_reload_keeps_rules_and_records_error(
    store: RulesStore, rules_path: Path
) -> None:
    active = store.current()
    before = sample("risk_rules_reloads_total", trigger="watcher", result="invalid")
    _write(rules_path, TEST_RULES.replace("price_collar_pct: 5", "price_collar_pct: -5"))

    with pytest.raises(RulesError):
        await store.reload(trigger="watcher")

    assert store.current() is active
    assert store.last_error is not None
    assert store.last_error.problems[0].startswith("defaults.price_collar_pct")
    assert sample("risk_rules_file_valid") == 0
    assert sample("risk_rules_reloads_total", trigger="watcher", result="invalid") == before + 1

    _write(rules_path, TEST_RULES)  # fixed again
    await store.reload(trigger="watcher")
    assert store.last_error is None
    assert sample("risk_rules_file_valid") == 1
