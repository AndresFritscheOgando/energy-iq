"""Fixtures for API tests against PostgreSQL (spec 0009/0002, 0009/0004); see ``dbsupport``."""

from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

import pytest
from dbsupport import (
    CSRF,
    PASSWORD,
    Clock,
    Probe,
    Scratch,
    TwoUsers,
    build_holdings,
    with_database,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.pool import NullPool

from energyiq.platform.clock import get_now
from energyiq.platform.settings import Settings

APP_ROLE = "energyiq_app"


@pytest.fixture
def clock(db_app: FastAPI) -> Clock:
    frozen = Clock()
    db_app.dependency_overrides[get_now] = lambda: frozen.now
    return frozen


@pytest.fixture
def new_client(db_app: FastAPI, clock: Clock) -> Callable[[], TestClient]:
    """A fresh client (its own cookie jar) that sends the CSRF header."""

    def build() -> TestClient:
        return TestClient(db_app, headers=CSRF)

    return build


@pytest.fixture
def api(new_client: Callable[[], TestClient]) -> TestClient:
    return new_client()


Register = Callable[..., dict[str, Any]]


@pytest.fixture
def register() -> Register:
    """Register through the API and return the ``UserOut`` body."""

    def run(
        client: TestClient, email: str = "owner@example.test", password: str = PASSWORD
    ) -> dict[str, Any]:
        response = client.post(
            "/api/v1/auth/register", json={"email": email, "password": password}
        )
        assert response.status_code == 201, response.text
        return response.json()

    return run


@pytest.fixture
def owner(api: TestClient, register: Register) -> dict[str, Any]:
    """``api`` signed in as a registered owner."""
    return register(api)


@pytest.fixture
def probe(db_connection: Connection) -> Probe:
    return Probe(db_connection)


# Two owners (spec 0009/0004 AC-1, AC-2) ---------------------------------------


@pytest.fixture
def two_users(new_client: Callable[[], TestClient], register: Register) -> TwoUsers:
    """Users A and B (separate cookie jars, CSRF header preset), plus A's archive."""
    client_a, client_b = new_client(), new_client()
    user_a = register(client_a, "alice@example.test")["id"]
    user_b = register(client_b, "bruno@example.test")["id"]
    a = build_holdings(client_a, user_a, "Casa A")
    b = build_holdings(client_b, user_b, "Casa B")
    archived = build_holdings(client_a, user_a, "Old A")
    response = client_a.delete(f"/api/v1/properties/{archived.property_id}")
    assert response.status_code == 204, response.text
    return TwoUsers(a, b, archived)


# Committed transactions (spec 0009/0004 AC-5) ---------------------------------


def _truncate(migrator_engine: Engine) -> None:
    with migrator_engine.begin() as connection:
        tables = connection.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                " AND tablename <> 'alembic_version' ORDER BY tablename"
            )
        ).scalars()
        connection.execute(
            text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
        )


@pytest.fixture
def committed_db(migrator_engine: Engine, app_engine: Engine) -> Iterator[Engine]:
    """No outer transaction: requests commit for real. Every app table is
    truncated as the migrator before and after the test (``*_test`` only, see
    ``require_test_database``). Yields the app role engine for side
    connections that hold locks or watch ``pg_stat_activity``."""
    _truncate(migrator_engine)
    try:
        yield app_engine
    finally:
        _truncate(migrator_engine)


# Scratch databases (spec 0009/0001 AC-5, 0009/0004 AC-6, AC-7) ----------------


@pytest.fixture
def scratch(migrator_engine: Engine, db_settings: Settings) -> Iterator[Scratch]:
    """A new empty database owned by the migrator, dropped even on failure.

    Database and schema privileges match ``infra/db/init/01-roles.sh``, so
    table privileges come from the Alembic revisions alone.
    """
    name = f"energyiq_migr_{uuid4().hex[:8]}"
    admin = migrator_engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    migrator_dsn = with_database(
        db_settings.migration_database_url.get_secret_value(), name
    )
    app_dsn = with_database(db_settings.database_url.get_secret_value(), name)
    try:
        with admin.connect() as connection:
            connection.execute(text(f'REVOKE ALL ON DATABASE "{name}" FROM PUBLIC'))
            connection.execute(
                text(f'GRANT CONNECT ON DATABASE "{name}" TO {APP_ROLE}')
            )
        engine = create_engine(migrator_dsn, poolclass=NullPool)
        try:
            with engine.begin() as connection:
                connection.execute(text("REVOKE ALL ON SCHEMA public FROM PUBLIC"))
                connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))
        finally:
            engine.dispose()
        yield Scratch(
            name=name,
            settings=Settings(
                env="test",
                database_url=SecretStr(app_dsn),
                migration_database_url=SecretStr(migrator_dsn),
            ),
            migrator_dsn=migrator_dsn,
            app_dsn=app_dsn,
        )
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
