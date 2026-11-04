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

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Connection, create_engine, make_url, text
from sqlalchemy.pool import NullPool

from energyiq.platform.db import alembic_config, connect_args
from energyiq.platform.settings import Settings

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


# Two owners (spec 0009/0004 AC-1, AC-2) ---------------------------------------


@dataclass(frozen=True)
class Holdings:
    """One owner's signed in client and one row of each owned kind."""

    client: TestClient
    user_id: str
    property_id: str
    meter_id: str
    reading_id: str
    event_id: str

    def ids(self) -> dict[str, str]:
        return {
            "property_id": self.property_id,
            "meter_id": self.meter_id,
            "reading_id": self.reading_id,
            "event_id": self.event_id,
        }


@dataclass(frozen=True)
class TwoUsers:
    a: Holdings
    b: Holdings
    archived: Holdings  # A's archived property, with its meter, reading, event


def created(response: Any) -> str:
    assert response.status_code == 201, response.text
    return response.json()["id"]


def build_holdings(client: TestClient, user_id: str, nickname: str) -> Holdings:
    """A property with an active meter, one reading, and one pending event."""
    property_id = created(
        client.post("/api/v1/properties", json={"nickname": nickname})
    )
    meter_id = created(
        client.post(
            f"/api/v1/properties/{property_id}/meters",
            json={"distributor": "EDESUR", "label": "Main"},
        )
    )
    reading_id = created(
        client.post(
            f"/api/v1/meters/{meter_id}/readings",
            json={"recorded_at": "2026-11-01T12:00:00Z", "cumulative_kwh": "100"},
        )
    )
    event_id = created(
        client.post(
            f"/api/v1/meters/{meter_id}/events",
            json={"event_type": "reset", "effective_at": "2026-11-02T12:00:00Z"},
        )
    )
    return Holdings(client, user_id, property_id, meter_id, reading_id, event_id)


# Scratch databases (spec 0009/0001 AC-5, 0009/0004 AC-6, AC-7) ---------------


@dataclass(frozen=True)
class Scratch:
    """An empty database for one test, created and dropped by the migrator."""

    name: str
    settings: Settings
    migrator_dsn: str
    app_dsn: str


def with_database(dsn: str, database: str) -> str:
    return make_url(dsn).set(database=database).render_as_string(hide_password=False)


def migrate(dsn: str, target: str, *, down: bool = False) -> None:
    """Run ``alembic upgrade`` (or ``downgrade``) on one database, then commit."""
    engine = create_engine(dsn, poolclass=NullPool, connect_args=connect_args(5000))
    config = alembic_config()
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            if down:
                command.downgrade(config, target)
            else:
                command.upgrade(config, target)
            connection.commit()
    finally:
        engine.dispose()


def current_revision(dsn: str) -> str | None:
    """The single ``alembic_version`` row, or ``None`` when there is none."""
    engine = create_engine(dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
            ).scalar_one()
            if not exists:
                return None
            return connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
    finally:
        engine.dispose()
