"""Environment-driven configuration.

All settings are read from environment variables (or a local ``.env`` file).
Names are unprefixed, e.g. ``REDIS_URL``, ``RULES_PATH``.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, RedisDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

MIN_KEY_LENGTH = 16


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_name: str = "pre-trade-risk-service"

    # rediss://user:password@host:6380/0?ssl_cert_reqs=required&ssl_ca_certs=/ca.pem for TLS.
    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")
    # Keeps the password out of the URL. A password in REDIS_URL takes precedence.
    redis_password: SecretStr | None = None
    redis_socket_timeout_seconds: float = Field(default=0.25, gt=0)

    rules_path: Path = Path("config/rules.yaml")
    # Edits take effect within about two intervals (one to see the change, one to
    # confirm the file has finished being written).
    rules_reload_interval_seconds: float = Field(default=1.0, gt=0)
    rules_watch_enabled: bool = True

    log_level: LogLevel = "INFO"
    log_json: bool = True

    health_check_timeout_seconds: float = Field(default=0.5, gt=0)

    # Keys accepted in X-API-Key on /v1/*, comma-separated so a new key can be
    # rolled out before the old one is removed. Required unless auth is
    # explicitly disabled for local development.
    api_keys: SecretStr | None = None
    api_auth_disabled: bool = False

    # Admin endpoints are disabled unless a key is configured.
    admin_api_key: SecretStr | None = None

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("admin_api_key", "api_keys", "redis_password", mode="before")
    @classmethod
    def _blank_secret_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _check_keys(self) -> Self:
        if not self.api_auth_disabled and not self.api_key_values:
            raise ValueError(
                "API_KEYS must be set (comma-separated client keys), "
                "or set API_AUTH_DISABLED=true for local development"
            )
        keys = list(self.api_key_values)
        if self.admin_api_key is not None:
            keys.append(self.admin_api_key.get_secret_value())
        if any(len(key) < MIN_KEY_LENGTH for key in keys):
            raise ValueError(f"API and admin keys must be at least {MIN_KEY_LENGTH} characters")
        return self

    @property
    def api_key_values(self) -> tuple[str, ...]:
        if self.api_keys is None:
            return ()
        return tuple(k.strip() for k in self.api_keys.get_secret_value().split(",") if k.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
