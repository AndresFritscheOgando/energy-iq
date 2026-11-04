"""Readiness endpoint: is a migrated database reachable? (spec 0009/0001 AC-5)."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from energyiq.platform.http.problems import Problem, ProblemError, problem_responses

READINESS_TIMEOUT_MS = 2000


class ReadyResponse(BaseModel):
    """Body of ``GET /health/ready``."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ready"]
    schema_revision: str


router = APIRouter(tags=["health"])


def _database_revision(engine: Engine) -> str | None:
    """The stamped revision, or ``None`` when ``alembic_version`` is missing
    or empty. Connection failures propagate as ``OperationalError``."""
    with engine.connect() as connection, connection.begin():
        connection.execute(
            text(f"SET LOCAL statement_timeout = {READINESS_TIMEOUT_MS}")
        )
        exists = connection.execute(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        ).scalar_one()
        if not exists:
            return None
        return connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()


@router.get(
    "/health/ready",
    responses=problem_responses(Problem, [503]),
)
def ready(request: Request) -> ReadyResponse:
    """Report ready when the database answers and its schema is at head."""
    engine: Engine = request.app.state.readiness_engine
    expected: str = request.app.state.schema_head
    try:
        revision = _database_revision(engine)
    except (OperationalError, PoolTimeoutError):
        raise ProblemError(503, "database_unavailable") from None
    except ProgrammingError:
        # The role cannot read the table: treat it like a missing table.
        revision = None
    if revision is None or revision != expected:
        raise ProblemError(503, "schema_out_of_date")
    return ReadyResponse(status="ready", schema_revision=revision)
