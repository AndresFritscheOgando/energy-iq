"""Database engine, declarative base, request sessions, and error mapping.

Spec 0009/0001. The engine connects lazily, so ``create_app`` and
``GET /health`` work with no database. Every connection runs in UTC with the
configured statement timeout. Sessions never commit on their own: each write
use case opens one ``with session.begin():`` (umbrella transaction rules).
"""

import logging
from collections.abc import Iterable, Iterator, Mapping
from functools import cache
from pathlib import Path
from typing import Annotated

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI, Request
from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from starlette.responses import Response

from energyiq.platform.http.problems import (
    ProblemError,
    problem_response,
    request_id_from,
)
from energyiq.platform.logging import ERROR_LOGGER
from energyiq.platform.settings import Settings

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
}

ALEMBIC_DIR = Path(__file__).resolve().parents[3] / "alembic"
POOL_TIMEOUT_SECONDS = 5
CONNECT_TIMEOUT_SECONDS = 2

_error_log = logging.getLogger(ERROR_LOGGER)


class Base(DeclarativeBase):
    """Declarative base whose constraint names follow ``NAMING_CONVENTION``."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def connect_args(statement_timeout_ms: int) -> dict[str, object]:
    """psycopg options: UTC session time zone and a statement timeout."""
    return {
        "connect_timeout": CONNECT_TIMEOUT_SECONDS,
        "options": f"-c timezone=UTC -c statement_timeout={statement_timeout_ms}",
    }


def build_engine(
    settings: Settings,
    *,
    pool_size: int | None = None,
    pool_timeout: float = POOL_TIMEOUT_SECONDS,
) -> Engine:
    """App role engine; no connection is opened until first use.

    ``hide_parameters`` keeps bound values out of SQLAlchemy's exception
    text. PostgreSQL's own ``DETAIL`` line still names the key value of a
    unique violation, so an ``IntegrityError`` must be mapped by constraint
    name and never logged as text (child 0002 owns that handling).
    """
    return create_engine(
        settings.database_url.get_secret_value(),
        hide_parameters=True,
        pool_size=pool_size or settings.db_pool_size,
        pool_pre_ping=True,
        pool_timeout=pool_timeout,
        connect_args=connect_args(settings.db_statement_timeout_ms),
    )


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def alembic_config() -> Config:
    """Alembic config pointing at ``backend/alembic``, without ``alembic.ini``."""
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    return config


@cache
def script_head() -> str:
    """The single head revision of the migration scripts."""
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if head is None:
        raise RuntimeError("the Alembic script directory has no head revision")
    return head


def get_db_session(request: Request) -> Iterator[Session]:
    """One session per request; closed after the response, never committed."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    session = factory()
    try:
        yield session
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db_session)]
"""The request's session; routes open their own ``with session.begin():``."""


def constraint_name(exc: IntegrityError) -> str | None:
    """The violated constraint's name, as reported by PostgreSQL."""
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return name if isinstance(name, str) else None


class UnmappedIntegrityError(RuntimeError):
    """An integrity violation no route expects; carries the name only."""


def integrity_problem(
    exc: IntegrityError, conflicts: Mapping[str, tuple[int, str]]
) -> Exception:
    """The problem for a violated constraint, mapped by its name.

    The ``IntegrityError`` text holds PostgreSQL's ``DETAIL`` line, which
    names the duplicate value (an email, a nickname). Callers raise the
    result ``from None``, so that text never reaches a log or a traceback.
    """
    name = constraint_name(exc)
    if name is not None and name in conflicts:
        status, code = conflicts[name]
        return ProblemError(status, code)
    return UnmappedIntegrityError(f"unmapped integrity violation: {name}")


async def _handle_database_unavailable(request: Request, exc: Exception) -> Response:
    """503 for connection failures, pool timeouts, and statement timeouts.

    The log line carries the request id and the exception class only: the
    exception text can hold the host, role, SQL, and bound parameters.
    """
    request_id = request_id_from(request.scope)
    _error_log.warning(
        "database unavailable: %s",
        type(exc).__name__,
        extra={"request_id": request_id},
    )
    return problem_response(503, "database_unavailable", request_id)


def install_database_handlers(app: FastAPI) -> None:
    """Map operational database errors to 503 ``database_unavailable``."""
    app.add_exception_handler(OperationalError, _handle_database_unavailable)
    app.add_exception_handler(PoolTimeoutError, _handle_database_unavailable)


def in_values(column: str, values: Iterable[str]) -> str:
    """SQL for a CHECK that ``column`` holds one of ``values`` (literal list)."""
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"
