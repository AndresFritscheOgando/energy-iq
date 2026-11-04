"""Application settings read from ``ENERGYIQ_*`` environment variables."""

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import (
    Field,
    PositiveInt,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_CORS_ORIGINS = ["http://localhost:3000"]
DEV_TRUSTED_ORIGINS = ["http://localhost:3000"]

# Synthetic local values matching ``infra/.env.example`` (spec 0009/0001 AC-1).
# ``prod`` never falls back to these: each must be set explicitly there.
_LOCAL_DSN = "postgresql+psycopg://{role}:{password}@127.0.0.1:5432/{database}"
_LOCAL_DATABASES: Mapping[str, str] = {"dev": "energyiq_dev", "test": "energyiq_test"}
_LOCAL_APP_PASSWORD = "energyiq-local-app"
_LOCAL_MIGRATOR_PASSWORD = "energyiq-local-migrator"
LOCAL_SECRET_KEY = "energyiq-local-secret-key-synthetic-not-for-prod"

# Marks a secret nobody set. A plain required field would make every
# ``Settings(env="test")`` call a type error, so the fields default to this
# sentinel and ``_required`` turns it into a ``missing`` error.
_UNSET = SecretStr("")


def local_database_url(env: str, *, migrator: bool = False) -> str:
    """The ``dev`` or ``test`` DSN for the Compose database.

    An unknown ``env`` gets the ``dev`` DSN so its own validation error is the
    only one reported.
    """
    if migrator:
        role, password = "energyiq_migrator", _LOCAL_MIGRATOR_PASSWORD
    else:
        role, password = "energyiq_app", _LOCAL_APP_PASSWORD
    database = _LOCAL_DATABASES.get(env, _LOCAL_DATABASES["dev"])
    return _LOCAL_DSN.format(role=role, password=password, database=database)


class Settings(BaseSettings):
    """Validated runtime configuration; invalid values fail at startup.

    In ``prod`` the database URLs, the secret key, and the trusted origins
    have no default, so a missing one fails with a ``missing`` error naming
    the field. Secrets are ``SecretStr`` and render as ``**********`` in
    ``repr`` and logs.
    """

    model_config = SettingsConfigDict(env_prefix="ENERGYIQ_", frozen=True)

    env: Literal["dev", "test", "prod"] = "dev"
    max_body_bytes: PositiveInt = 1_048_576
    cors_origins: list[str] = []
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: SecretStr = Field(default=_UNSET, min_length=1, validate_default=True)
    migration_database_url: SecretStr = Field(
        default=_UNSET, min_length=1, validate_default=True
    )
    db_pool_size: Annotated[int, Field(ge=1, le=50)] = 5
    db_statement_timeout_ms: Annotated[int, Field(ge=100, le=60_000)] = 5000
    secret_key: SecretStr = Field(default=_UNSET, min_length=32, validate_default=True)

    # Spec 0009/0002: session cookie and the CSRF ``Origin`` allow list.
    session_cookie_secure: bool = False
    trusted_origins: list[str] = Field(default_factory=list[str], validate_default=True)

    @field_validator(
        "database_url", "migration_database_url", "secret_key", mode="before"
    )
    @classmethod
    def _required(cls, value: object) -> object:
        """Report an unset secret as ``missing``, naming the field."""
        if value is _UNSET:
            raise PydanticCustomError("missing", "Field required")
        return value

    @field_validator("trusted_origins")
    @classmethod
    def _trusted_origins_in_prod(
        cls, value: list[str], info: ValidationInfo
    ) -> list[str]:
        """``prod`` must name the browser origin (the Next.js proxy) explicitly."""
        if info.data.get("env") == "prod" and not value:
            raise PydanticCustomError("missing", "Field required")
        return [origin.lower() for origin in value]

    @model_validator(mode="before")
    @classmethod
    def _environment_defaults(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Fill the per environment defaults for values left unset."""
        env = data.get("env", "dev")
        defaults: dict[str, Any] = {
            "cors_origins": [] if env == "prod" else list(DEV_CORS_ORIGINS),
            "session_cookie_secure": env == "prod",
        }
        if env != "prod":
            defaults["trusted_origins"] = list(DEV_TRUSTED_ORIGINS)
            defaults["database_url"] = local_database_url(env)
            defaults["migration_database_url"] = local_database_url(env, migrator=True)
            defaults["secret_key"] = LOCAL_SECRET_KEY
        return {**defaults, **data}
