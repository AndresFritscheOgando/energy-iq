"""Application settings read from ``ENERGYIQ_*`` environment variables."""

from typing import Any, Literal

from pydantic import PositiveInt, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_CORS_ORIGINS = ["http://localhost:3000"]


class Settings(BaseSettings):
    """Validated runtime configuration; invalid values fail at startup."""

    model_config = SettingsConfigDict(env_prefix="ENERGYIQ_", frozen=True)

    env: Literal["dev", "test", "prod"] = "dev"
    max_body_bytes: PositiveInt = 1_048_576
    cors_origins: list[str] = []
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @model_validator(mode="before")
    @classmethod
    def _default_cors_origins(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Default CORS origins by environment when none are configured."""
        if "cors_origins" not in data:
            env = data.get("env", "dev")
            origins = [] if env == "prod" else list(DEV_CORS_ORIGINS)
            return {**data, "cors_origins": origins}
        return data
