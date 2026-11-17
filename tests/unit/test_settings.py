from pathlib import Path

import pytest
from pydantic import ValidationError

from risk_service.main import _redact
from risk_service.settings import Settings


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_defaults() -> None:
    s = _settings()
    assert str(s.redis_url) == "redis://localhost:6379/0"
    assert s.rules_path == Path("config/rules.yaml")
    assert s.admin_api_key is None


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://cache:6380/2")
    monkeypatch.setenv("RULES_PATH", "/etc/risk/rules.yaml")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("ADMIN_API_KEY", "s3cret")

    s = _settings()

    assert str(s.redis_url) == "redis://cache:6380/2"
    assert s.rules_path == Path("/etc/risk/rules.yaml")
    assert s.log_level == "DEBUG"
    assert s.admin_api_key is not None
    assert s.admin_api_key.get_secret_value() == "s3cret"


def test_blank_admin_key_disables_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", "   ")
    assert _settings().admin_api_key is None


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("REDIS_URL", "http://not-redis"),
        ("RULES_RELOAD_INTERVAL_SECONDS", "0"),
        ("LOG_LEVEL", "LOUD"),
    ],
)
def test_invalid_env_is_rejected(monkeypatch: pytest.MonkeyPatch, var: str, value: str) -> None:
    monkeypatch.setenv(var, value)
    with pytest.raises(ValidationError):
        _settings()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("redis://localhost:6379/0", "redis://localhost:6379/0"),
        ("redis://:pw@host:6379/0", "redis://:***@host:6379/0"),
        ("redis://user:pw@host:6379/0", "redis://user:***@host:6379/0"),
    ],
)
def test_redact_hides_password(url: str, expected: str) -> None:
    assert _redact(url) == expected
