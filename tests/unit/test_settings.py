from pathlib import Path

import pytest
from pydantic import ValidationError
from redis.asyncio import SSLConnection

from risk_service.main import _redact, create_redis
from risk_service.settings import Settings

KEY_A = "client-key-aaaaaaaa"
KEY_B = "client-key-bbbbbbbb"


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_defaults_with_auth_disabled() -> None:
    s = _settings(api_auth_disabled=True)
    assert str(s.redis_url) == "redis://localhost:6379/0"
    assert s.rules_path == Path("config/rules.yaml")
    assert s.admin_api_key is None
    assert s.api_key_values == ()


def test_api_keys_are_required_unless_auth_is_disabled() -> None:
    with pytest.raises(ValidationError, match="API_KEYS must be set"):
        _settings()


def test_api_keys_allow_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEYS", f" {KEY_A} , {KEY_B},, ")
    assert _settings().api_key_values == (KEY_A, KEY_B)


@pytest.mark.parametrize("var", ["API_KEYS", "ADMIN_API_KEY"])
def test_short_keys_are_rejected(monkeypatch: pytest.MonkeyPatch, var: str) -> None:
    monkeypatch.setenv("API_KEYS", KEY_A)
    monkeypatch.setenv(var, "short")
    with pytest.raises(ValidationError, match="at least 16 characters"):
        _settings()


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://cache:6380/2")
    monkeypatch.setenv("RULES_PATH", "/etc/risk/rules.yaml")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("API_KEYS", KEY_A)
    monkeypatch.setenv("ADMIN_API_KEY", "admin-key-cccccccc")

    s = _settings()

    assert str(s.redis_url) == "redis://cache:6380/2"
    assert s.rules_path == Path("/etc/risk/rules.yaml")
    assert s.log_level == "DEBUG"
    assert s.admin_api_key is not None
    assert s.admin_api_key.get_secret_value() == "admin-key-cccccccc"


@pytest.mark.parametrize("var", ["ADMIN_API_KEY", "REDIS_PASSWORD"])
def test_blank_secrets_are_unset(monkeypatch: pytest.MonkeyPatch, var: str) -> None:
    monkeypatch.setenv(var, "   ")
    s = _settings(api_auth_disabled=True)
    assert s.admin_api_key is None
    assert s.redis_password is None


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
        _settings(api_auth_disabled=True)


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


async def test_tls_options_in_url_reach_the_connection_pool() -> None:
    s = _settings(
        api_auth_disabled=True,
        redis_url=(
            "rediss://risk-service:pw@redis.internal:6380/0"
            "?ssl_cert_reqs=required&ssl_ca_certs=/etc/ssl/redis-ca.pem"
        ),
    )
    client = create_redis(s)
    pool = client.connection_pool
    try:
        assert pool.connection_class is SSLConnection
        assert pool.connection_kwargs["ssl_cert_reqs"] == "required"
        assert pool.connection_kwargs["ssl_ca_certs"] == "/etc/ssl/redis-ca.pem"
        assert pool.connection_kwargs["username"] == "risk-service"
        assert pool.connection_kwargs["password"] == "pw"
    finally:
        await client.aclose()


async def test_redis_password_setting_keeps_secret_out_of_url() -> None:
    s = _settings(
        api_auth_disabled=True,
        redis_url="redis://risk-service@redis.internal:6379/0",
        redis_password="from-a-secret-store",
    )
    client = create_redis(s)
    try:
        assert client.connection_pool.connection_kwargs["password"] == "from-a-secret-store"
        assert client.connection_pool.connection_kwargs["username"] == "risk-service"
    finally:
        await client.aclose()
