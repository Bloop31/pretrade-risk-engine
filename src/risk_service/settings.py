"""Environment-driven configuration.

All settings are read from environment variables (or a local ``.env`` file).
Names are unprefixed, e.g. ``REDIS_URL``, ``RULES_PATH``.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, RedisDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_name: str = "pre-trade-risk-service"

    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")
    redis_socket_timeout_seconds: float = Field(default=0.25, gt=0)

    rules_path: Path = Path("config/rules.yaml")
    # Edits take effect within about two intervals (one to see the change, one to
    # confirm the file has finished being written).
    rules_reload_interval_seconds: float = Field(default=1.0, gt=0)
    rules_watch_enabled: bool = True

    log_level: LogLevel = "INFO"
    log_json: bool = True

    health_check_timeout_seconds: float = Field(default=0.5, gt=0)

    # Admin endpoints are disabled unless a key is configured.
    admin_api_key: SecretStr | None = None

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("admin_api_key", mode="before")
    @classmethod
    def _blank_key_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
