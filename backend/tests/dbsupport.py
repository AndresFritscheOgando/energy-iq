"""Helpers for API tests against PostgreSQL (spec 0009/0002). Synthetic data only.

Every request runs in the rolled back test transaction (``db_app``), so a
route's ``with session.begin():`` is a savepoint. ``Probe`` reads through
the same connection, never through the app's session, so it never opens a
transaction the next request's ``begin()`` would trip on.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

CSRF = {"X-EnergyIQ-CSRF": "1"}
PASSWORD = "correct horse battery"
START = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@dataclass
class Clock:
    """The instant every route sees; tests move it explicitly."""

    now: datetime = field(default=START)

    def advance(self, **delta: float) -> datetime:
        self.now += timedelta(**delta)
        return self.now


class Probe:
    """Reads the test transaction as plain dicts, beside the app's session."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def rows(
        self, sql: str, params: Mapping[str, object] | None = None
    ) -> list[dict[str, Any]]:
        result = self.connection.execute(text(sql), dict(params or {}))
        return [dict(row) for row in result.mappings()]

    def one(self, sql: str, params: Mapping[str, object] | None = None) -> Any:
        return self.connection.execute(text(sql), dict(params or {})).scalar_one()

    def run(self, sql: str, params: Mapping[str, object] | None = None) -> None:
        self.connection.execute(text(sql), dict(params or {}))

    def audit(self, entity_id: UUID | str) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT actor_user_id, action, entity_type, entity_id, request_id,"
            " metadata FROM audit_events WHERE entity_id = :id ORDER BY id",
            {"id": str(entity_id)},
        )


def without_request_id(body: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in body.items() if key != "request_id"}
