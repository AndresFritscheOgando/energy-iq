"""Readiness and connection settings against real PostgreSQL (spec 0009/0001).

AC-5: ready at head, out of date without or below head. AC-6: every connection
runs in UTC with the configured statement timeout, and a timeout answers 503.
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated
from uuid import uuid4

import pytest
from alembic import command
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from energyiq.main import create_app
from energyiq.platform.db import (
    alembic_config,
    connect_args,
    get_db_session,
    script_head,
)
from energyiq.platform.settings import Settings

pytestmark = pytest.mark.db


@dataclass(frozen=True)
class Scratch:
    settings: Settings
    migrator_dsn: str


def _with_database(dsn: str, database: str) -> str:
    return make_url(dsn).set(database=database).render_as_string(hide_password=False)


@pytest.fixture
def scratch(migrator_engine: Engine, db_settings: Settings) -> Iterator[Scratch]:
    """A new empty database owned by the migrator, dropped afterwards."""
    name = f"energyiq_scratch_{uuid4().hex[:12]}"
    admin = migrator_engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    migrator_dsn = _with_database(
        db_settings.migration_database_url.get_secret_value(), name
    )
    app_dsn = _with_database(db_settings.database_url.get_secret_value(), name)
    try:
        yield Scratch(
            settings=Settings(
                env="test",
                database_url=SecretStr(app_dsn),
                migration_database_url=SecretStr(migrator_dsn),
            ),
            migrator_dsn=migrator_dsn,
        )
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))


def _migrate(dsn: str, target: str, *, down: bool = False) -> None:
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


def _ready(settings: Settings) -> tuple[int, dict[str, object]]:
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
    return response.status_code, response.json()


def test_ready_at_head(db_settings: Settings) -> None:
    status, body = _ready(db_settings)

    assert status == 200
    assert body == {"status": "ready", "schema_revision": script_head()}


def test_out_of_date_through_the_migration_lifecycle(scratch: Scratch) -> None:
    """No version table, then head, then ``downgrade base`` (AC-5)."""
    before = _ready(scratch.settings)
    _migrate(scratch.migrator_dsn, "head")
    migrated = _ready(scratch.settings)
    _migrate(scratch.migrator_dsn, "base", down=True)
    downgraded = _ready(scratch.settings)

    assert before[0] == 503
    assert before[1]["code"] == "schema_out_of_date"
    assert before[1]["detail"] == "The database schema is not up to date."
    assert migrated == (200, {"status": "ready", "schema_revision": script_head()})
    assert downgraded[0] == 503
    assert downgraded[1]["code"] == "schema_out_of_date"


def test_downgrade_base_removes_every_table(scratch: Scratch) -> None:
    _migrate(scratch.migrator_dsn, "head")
    _migrate(scratch.migrator_dsn, "base", down=True)

    engine = create_engine(scratch.migrator_dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            tables = connection.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                    " AND tablename <> 'alembic_version'"
                )
            ).all()
    finally:
        engine.dispose()

    assert tables == []


def _probe_app(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.get("/_probe/settings")
    def probe_settings(  # pyright: ignore[reportUnusedFunction]
        session: Annotated[Session, Depends(get_db_session)],
    ) -> dict[str, str]:
        with session.begin():
            timezone = session.execute(text("SHOW timezone")).scalar_one()
            timeout = session.execute(text("SHOW statement_timeout")).scalar_one()
        return {"timezone": str(timezone), "statement_timeout": str(timeout)}

    @app.get("/_probe/sleep")
    def probe_sleep(  # pyright: ignore[reportUnusedFunction]
        session: Annotated[Session, Depends(get_db_session)],
    ) -> dict[str, str]:
        with session.begin():
            session.execute(text("SELECT pg_sleep(2)"))
        return {}

    return app


def test_connections_use_utc_and_the_configured_timeout(
    db_settings: Settings,
) -> None:
    settings = db_settings.model_copy(update={"db_statement_timeout_ms": 1500})

    with TestClient(_probe_app(settings)) as client:
        body = client.get("/_probe/settings").json()

    assert body == {"timezone": "UTC", "statement_timeout": "1500ms"}


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_statement_timeout_answers_503_without_leaking_sql(
    db_settings: Settings,
) -> None:
    settings = db_settings.model_copy(update={"db_statement_timeout_ms": 100})
    app = _probe_app(settings)
    handler = _ListHandler()
    logger = logging.getLogger("energyiq.errors")
    logger.addHandler(handler)
    try:
        with TestClient(app) as client:
            response = client.get("/_probe/sleep")
    finally:
        logger.removeHandler(handler)

    body = response.json()
    assert response.status_code == 503
    assert body["code"] == "database_unavailable"
    assert response.headers["x-request-id"] == body["request_id"]
    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.__dict__["request_id"] == body["request_id"]
    assert record.exc_info is None
    logged = record.getMessage()
    assert logged == "database unavailable: OperationalError"
