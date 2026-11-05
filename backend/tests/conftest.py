"""Shared pytest configuration: Hypothesis profiles and database fixtures.

``ENERGYIQ_HYPOTHESIS_PROFILE`` picks the profile. The default ``energyiq``
profile is derandomized and keeps no example database, so every run tries the
same examples. ``deep`` searches 2000 random examples per property and keeps
the local example database. The profile is loaded explicitly so that
Hypothesis never switches to its own ``ci`` profile when a ``CI`` variable is
set. An unknown name raises ``InvalidArgument`` and stops the session.
"""

import os
from collections.abc import Callable, Iterator
from datetime import datetime

import pytest
from alembic import command
from fastapi import FastAPI
from hypothesis import settings
from sqlalchemy import Connection, Engine, create_engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from energyiq.main import create_app
from energyiq.platform.db import (
    alembic_config,
    build_engine,
    connect_args,
    get_db_session,
)
from energyiq.platform.settings import Settings as AppSettings

PROFILE_ENV_VAR = "ENERGYIQ_HYPOTHESIS_PROFILE"
DEFAULT_PROFILE = "energyiq"

# Inherit from the built in default, never from whichever profile Hypothesis
# auto loaded (its ``ci`` profile suppresses a health check).
_BASE = settings.get_profile("default")

settings.register_profile(
    "energyiq",
    parent=_BASE,
    max_examples=200,
    derandomize=True,
    database=None,
    deadline=None,
    print_blob=True,
)
settings.register_profile(
    "deep",
    parent=_BASE,
    max_examples=2000,
    derandomize=False,
    deadline=None,
    print_blob=True,
)
settings.load_profile(os.environ.get(PROFILE_ENV_VAR, DEFAULT_PROFILE))


# Database and secret settings (spec 0009/0001 AC-8). A developer's shell must
# not leak into tests; ``prod_secrets`` provides the values prod requires.
SECRET_ENV_VARS = (
    "ENERGYIQ_DATABASE_URL",
    "ENERGYIQ_MIGRATION_DATABASE_URL",
    "ENERGYIQ_DB_POOL_SIZE",
    "ENERGYIQ_DB_STATEMENT_TIMEOUT_MS",
    "ENERGYIQ_SECRET_KEY",
    "ENERGYIQ_SESSION_COOKIE_SECURE",
    "ENERGYIQ_TRUSTED_ORIGINS",
    "ENERGYIQ_FORWARDED_ALLOW_IPS",
    "ENERGYIQ_DOCUMENT_ROOT",
)
PROD_SECRETS = {
    "ENERGYIQ_DATABASE_URL": "postgresql+psycopg://app:synthetic@db.invalid/prod",
    "ENERGYIQ_MIGRATION_DATABASE_URL": (
        "postgresql+psycopg://migrator:synthetic@db.invalid/prod"
    ),
    "ENERGYIQ_SECRET_KEY": "synthetic-prod-secret-key-for-tests-only",
    "ENERGYIQ_TRUSTED_ORIGINS": '["https://app.example"]',
    "ENERGYIQ_FORWARDED_ALLOW_IPS": '["10.0.0.5"]',
    "ENERGYIQ_DOCUMENT_ROOT": "/var/lib/energyiq/documents",
}


@pytest.fixture(autouse=True)
def clean_database_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SECRET_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def prod_secrets(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Set the variables ``env=prod`` requires to synthetic values."""
    for name, value in PROD_SECRETS.items():
        monkeypatch.setenv(name, value)
    return dict(PROD_SECRETS)


# PostgreSQL fixtures (spec 0009/0001 AC-7) ------------------------------------
#
# Tests marked ``db`` run against the Compose test database. If it is not
# reachable they are skipped with the reason, or fail when
# ``ENERGYIQ_REQUIRE_DB=1``. The schema is migrated to head once per session as
# the migrator role. Each test then runs as the app role inside an outer
# transaction that is rolled back, so tests never see each other's rows.

REQUIRE_DB_ENV_VAR = "ENERGYIQ_REQUIRE_DB"
# Read once at import, before the autouse fixture above clears the variables.
DB_SETTINGS = AppSettings(env="test")


TEST_DATABASE_SUFFIX = "_test"


def require_test_database(*dsns: str) -> None:
    """Stop the run unless every DSN names a ``*_test`` database.

    The fixtures migrate and create scratch databases, so a stray shell
    ``ENERGYIQ_*`` URL must never point them at dev or prod data.
    """
    for dsn in dsns:
        database = make_url(dsn).database or ""
        if not database.endswith(TEST_DATABASE_SUFFIX):
            pytest.fail(
                f"refusing to run db tests against {database_location(dsn)}: "
                f"the database name must end with {TEST_DATABASE_SUFFIX!r}",
                pytrace=False,
            )


def database_location(dsn: str) -> str:
    """``host:port/database`` of a DSN, without the role or password."""
    url = make_url(dsn)
    return f"{url.host}:{url.port or 5432}/{url.database}"


@pytest.fixture(scope="session")
def migrator_engine() -> Iterator[Engine]:
    """Migrator role engine; checks reachability, then migrates to head."""
    dsn = DB_SETTINGS.migration_database_url.get_secret_value()
    require_test_database(dsn, DB_SETTINGS.database_url.get_secret_value())
    engine = create_engine(
        dsn,
        poolclass=NullPool,
        connect_args=connect_args(DB_SETTINGS.db_statement_timeout_ms),
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        engine.dispose()
        reason = f"PostgreSQL not reachable at {database_location(dsn)}"
        if os.environ.get(REQUIRE_DB_ENV_VAR) == "1":
            pytest.fail(f"{reason} and {REQUIRE_DB_ENV_VAR}=1", pytrace=False)
        pytest.skip(reason)

    config = alembic_config()
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        connection.commit()
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(migrator_engine: Engine) -> Iterator[Engine]:
    """App role engine for the migrated test database."""
    engine = build_engine(DB_SETTINGS)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _require_database_for_db_marker(request: pytest.FixtureRequest) -> None:
    """Gate every ``db`` and ``db_commit`` test on the session database check."""
    node = request.node
    if node.get_closest_marker("db") or node.get_closest_marker("db_commit"):
        request.getfixturevalue("migrator_engine")


@pytest.fixture
def db_connection(app_engine: Engine) -> Iterator[Connection]:
    """App role connection inside an outer transaction rolled back after."""
    with app_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def db_session(db_connection: Connection) -> Iterator[Session]:
    """A session whose ``begin()`` and ``commit()`` use savepoints only."""
    session = Session(
        bind=db_connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def db_app(db_session: Session) -> FastAPI:
    """The app with ``get_db_session`` bound to the rolled back test session."""
    app = create_app(DB_SETTINGS)

    def override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db_session] = override
    return app


@pytest.fixture
def db_settings() -> AppSettings:
    """Settings for the test database (honours ``ENERGYIQ_*`` at import)."""
    return DB_SETTINGS


@pytest.fixture
def delete_committed_user(
    migrator_engine: Engine,
) -> Iterator[Callable[[str, datetime], None]]:
    """Delete what a committing test wrote for one user, as the migrator.

    Call it with the user's email and the instant the test started. It
    removes the user's audit rows, sessions, and row, plus every auth
    attempt since that instant (attempts carry no user id; only committing
    tests write them, because the others roll back).
    """

    def cleanup(email: str, since: datetime) -> None:
        with migrator_engine.begin() as connection:
            user_id = connection.execute(
                text("SELECT id FROM users WHERE email = :email"), {"email": email}
            ).scalar_one_or_none()
            connection.execute(
                text("DELETE FROM auth_attempts WHERE attempted_at >= :since"),
                {"since": since},
            )
            if user_id is None:
                return
            for sql in (
                "DELETE FROM audit_events WHERE actor_user_id = :id OR entity_id = :id",
                "DELETE FROM idempotency_keys WHERE user_id = :id",
                "DELETE FROM readings WHERE meter_id IN (SELECT m.id FROM meters m JOIN properties p ON p.id = m.property_id WHERE p.owner_user_id = :id)",
                "DELETE FROM meter_events WHERE meter_id IN (SELECT m.id FROM meters m JOIN properties p ON p.id = m.property_id WHERE p.owner_user_id = :id)",
                "DELETE FROM meters WHERE property_id IN (SELECT id FROM properties WHERE owner_user_id = :id)",
                "DELETE FROM properties WHERE owner_user_id = :id",
                "DELETE FROM sessions WHERE user_id = :id",
                "DELETE FROM users WHERE id = :id",
            ):
                connection.execute(text(sql), {"id": user_id})

    yield cleanup
