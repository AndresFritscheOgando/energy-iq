"""Application settings read from ``ENERGYIQ_*`` environment variables."""

import ipaddress
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

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
# Peers whose ``X-Forwarded-For`` is believed (spec 0010 AC-14): the local
# Next.js server. ``prod`` has no default and must list its proxies.
DEV_FORWARDED_ALLOW_IPS = ["127.0.0.1", "::1"]

# Synthetic local values matching ``infra/.env.example`` (spec 0009/0001 AC-1).
# ``prod`` never falls back to these: each must be set explicitly there.
_LOCAL_DSN = "postgresql+psycopg://{role}:{password}@127.0.0.1:5432/{database}"
_LOCAL_DATABASES: Mapping[str, str] = {"dev": "energyiq_dev", "test": "energyiq_test"}
_LOCAL_APP_PASSWORD = "energyiq-local-app"
_LOCAL_MIGRATOR_PASSWORD = "energyiq-local-migrator"
LOCAL_SECRET_KEY = "energyiq-local-secret-key-synthetic-not-for-prod"
# Private document directory for dev and test (git ignored). ``prod`` must name one.
LOCAL_DOCUMENT_ROOT = Path(__file__).resolve().parents[4] / ".local" / "documents"

MIB = 1024 * 1024
# Spec 0012/0002: each limit has a default and a hard ceiling, so a typo
# cannot disable a cap. The lease must outlast the parser wall clock limit.
LEASE_MARGIN_SECONDS = 30

# Marks a secret nobody set. A plain required field would make every
# ``Settings(env="test")`` call a type error, so the fields default to this
# sentinel and ``_required`` turns it into a ``missing`` error.
_UNSET = SecretStr("")


# The same marker for ``env``, which has no default in any environment: a
# deploy that forgets ``ENERGYIQ_ENV`` must fail, not run with dev settings.
class _Unset:
    """A readable stand in, so the ``missing`` error does not print an address."""

    def __repr__(self) -> str:
        return "<unset>"


_UNSET_ENV: Any = _Unset()


_NUMERIC_HOST = re.compile(r"(0x[0-9a-f]+|[0-9]+)(\.(0x[0-9a-f]+|[0-9]+))*")


def _is_local_host(host: str) -> bool:
    """Loopback, a private or link local address, ``localhost``, or a bare
    service name such as the Compose ``ollama`` (no dots, so no public DNS)."""
    host = host.lower()
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # "134744072" or "0x7f000001" are old spellings of an IP address that
        # the parser above does not read; never treat them as a service name.
        if _NUMERIC_HOST.fullmatch(host):
            return False
        return "." not in host
    # Link local (169.254.x.x) holds cloud metadata endpoints: not a model host.
    return (address.is_loopback or address.is_private) and not address.is_link_local


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

    ``env`` is required everywhere (no default), so an unset
    ``ENERGYIQ_ENV`` fails with a ``missing`` error naming ``env``.
    In ``prod`` the database URLs, the secret key, the trusted origins, and
    the forwarded allow list have no default, so a missing one fails with a ``missing`` error naming
    the field. Secrets are ``SecretStr`` and render as ``**********`` in
    ``repr`` and logs.
    """

    model_config = SettingsConfigDict(env_prefix="ENERGYIQ_", frozen=True)

    env: Literal["dev", "test", "prod"] = Field(
        default=_UNSET_ENV, validate_default=True
    )
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

    # Spec 0010 AC-14: IP addresses or CIDR ranges (never hostnames) of the
    # proxies allowed to set the client address. ``[]`` is valid in ``prod``
    # but must be written out; unset fails there.
    forwarded_allow_ips: list[str] = Field(default=_UNSET_ENV, validate_default=True)

    # Spec 0012/0002: private source PDFs and the bounded extraction worker.
    document_root: Path = Field(default=_UNSET_ENV, validate_default=True)
    worker_isolation: Literal["container", "none"] = "container"
    upload_max_bytes: Annotated[int, Field(gt=0, le=20 * MIB)] = 5 * MIB
    pdf_max_pages: Annotated[int, Field(gt=0, le=50)] = 10
    pdf_max_text_bytes: Annotated[int, Field(gt=0, le=MIB)] = 256 * 1024
    pdf_cpu_seconds: Annotated[int, Field(gt=0, le=60)] = 20
    pdf_wall_seconds: Annotated[int, Field(gt=0, le=120)] = 30
    pdf_memory_bytes: Annotated[int, Field(gt=0, le=2048 * MIB)] = 768 * MIB
    run_max_attempts: Annotated[int, Field(gt=0, le=5)] = 2
    doc_max_runs: Annotated[int, Field(gt=0, le=10)] = 3
    worker_concurrency: Annotated[int, Field(gt=0, le=4)] = 1
    owner_max_active_docs: Annotated[int, Field(gt=0, le=10)] = 3
    run_lease_seconds: Annotated[int, Field(gt=0, le=600)] = 90

    # Spec 0012/0004: optional local Ollama proposals. Off unless a person turns
    # it on and names the model; there is deliberately no default model.
    extraction_enabled: bool = False
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    ollama_timeout_seconds: Annotated[int, Field(gt=0, le=300)] = 30
    extraction_max_attempts: Annotated[int, Field(gt=0, le=3)] = 2
    # Bill text goes only to a local model. A remote host needs this stated.
    ollama_allow_remote: bool = False
    extraction_max_output_bytes: Annotated[int, Field(gt=0, le=MIB)] = 16 * 1024

    @field_validator(
        "env",
        "database_url",
        "migration_database_url",
        "secret_key",
        "forwarded_allow_ips",
        "document_root",
        mode="before",
    )
    @classmethod
    def _required(cls, value: object) -> object:
        """Report an unset ``env`` or secret as ``missing``, naming the field."""
        if value is _UNSET or value is _UNSET_ENV:
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

    @field_validator("forwarded_allow_ips")
    @classmethod
    def _ip_or_network(cls, value: list[str]) -> list[str]:
        """Each entry must parse as an IP address or a CIDR network."""
        for entry in value:
            try:
                if "/" in entry:
                    ipaddress.ip_network(entry)
                else:
                    ipaddress.ip_address(entry)
            except ValueError:
                raise PydanticCustomError(
                    "ip_or_network",
                    "Each entry must be an IP address or a CIDR network",
                ) from None
        return value

    @model_validator(mode="after")
    def _lease_outlasts_parser(self) -> "Settings":
        """A lease at or below the wall clock limit plus margin would let a
        second worker claim a run whose parser is still alive."""
        if self.run_lease_seconds <= self.pdf_wall_seconds + LEASE_MARGIN_SECONDS:
            raise PydanticCustomError(
                "lease_too_short",
                "run_lease_seconds must exceed pdf_wall_seconds plus 30",
            )
        return self

    @model_validator(mode="after")
    def _extraction_config(self) -> "Settings":
        """Ollama proposals need a named model, a plain local URL, and a lease
        that outlasts every model call (the worker renews it once, after parsing)."""
        if not self.extraction_enabled:
            return self
        if not self.ollama_model:
            raise PydanticCustomError(
                "missing", "ollama_model is required when extraction_enabled"
            )
        parts = urlsplit(self.ollama_base_url)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise PydanticCustomError(
                "ollama_base_url",
                "ollama_base_url must be a plain http(s) origin without credentials",
            )
        if not self.ollama_allow_remote and not _is_local_host(parts.hostname):
            raise PydanticCustomError(
                "ollama_base_url_not_local",
                "ollama_base_url must name this machine, a private address, or a"
                " single label service name; set ollama_allow_remote to override",
            )
        # Every attempt, the one digest lookup (5 s), and a retry pause of up to
        # 1 s each, plus the usual margin.
        attempts = self.extraction_max_attempts
        needed = self.ollama_timeout_seconds * attempts + 5 + attempts
        if self.run_lease_seconds <= needed + LEASE_MARGIN_SECONDS:
            raise PydanticCustomError(
                "lease_too_short_for_model",
                "run_lease_seconds must exceed ollama_timeout_seconds times"
                " extraction_max_attempts, plus 5 for the digest lookup, one"
                " second per attempt for retry pauses, and 30",
            )
        return self

    @model_validator(mode="before")
    @classmethod
    def _environment_defaults(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Fill the per environment defaults for values left unset."""
        env = data.get("env", "dev")
        defaults: dict[str, Any] = {
            "cors_origins": [] if env == "prod" else list(DEV_CORS_ORIGINS),
            "session_cookie_secure": env == "prod",
            "worker_isolation": "container" if env == "prod" else "none",
        }
        if env != "prod":
            defaults["trusted_origins"] = list(DEV_TRUSTED_ORIGINS)
            defaults["forwarded_allow_ips"] = list(DEV_FORWARDED_ALLOW_IPS)
            defaults["database_url"] = local_database_url(env)
            defaults["migration_database_url"] = local_database_url(env, migrator=True)
            defaults["secret_key"] = LOCAL_SECRET_KEY
            defaults["document_root"] = LOCAL_DOCUMENT_ROOT
        return {**defaults, **data}
