"""The app role's privileges come from the revisions alone (spec 0009/0004 AC-7).

A scratch database is migrated from empty, so no grant can be left over from
an earlier schema. Readings values and times and every audit row are append
only by privilege: the app role may insert and read them, and may update only
the granted status and decision columns.
"""

from collections.abc import Iterator

import psycopg.errors
import pytest
from dbsupport import CSRF, PASSWORD, Scratch, migrate
from fastapi.testclient import TestClient
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from energyiq.main import create_app

pytestmark = pytest.mark.db

APP_ROLE = "energyiq_app"

FORBIDDEN = [
    "DELETE FROM readings",
    "TRUNCATE readings",
    "CREATE TABLE x ()",
    "ALTER TABLE readings ADD COLUMN x integer",
    "DROP TABLE readings",
    "UPDATE readings SET cumulative_kwh = cumulative_kwh + 1",
    "UPDATE readings SET recorded_at = recorded_at",
    "UPDATE readings SET meter_id = meter_id",
    "UPDATE audit_events SET action = action",
    "UPDATE audit_events SET metadata = metadata",
    "DELETE FROM audit_events",
    "UPDATE meter_events SET effective_at = effective_at",
    "DELETE FROM users",
]


@pytest.fixture
def migrated(scratch: Scratch) -> Iterator[Scratch]:
    """Scratch at head, with one owner, meter, reading, and audit trail."""
    migrate(scratch.migrator_dsn, "head")
    with TestClient(create_app(scratch.settings), headers=CSRF) as client:
        assert (
            client.post(
                "/api/v1/auth/register",
                json={"email": "grants@example.test", "password": PASSWORD},
            ).status_code
            == 201
        )
        home = client.post("/api/v1/properties", json={"nickname": "Casa"}).json()
        meter = client.post(
            f"/api/v1/properties/{home['id']}/meters",
            json={"distributor": "EDESUR", "label": "Main"},
        ).json()
        reading = client.post(
            f"/api/v1/meters/{meter['id']}/readings",
            json={"recorded_at": "2026-10-01T12:00:00Z", "cumulative_kwh": "100"},
        )
        assert reading.status_code == 201, reading.text
    yield scratch


@pytest.fixture
def as_app(migrated: Scratch) -> Iterator[Connection]:
    engine = create_engine(migrated.app_dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            yield connection
    finally:
        engine.dispose()


@pytest.mark.parametrize("sql", FORBIDDEN)
def test_the_app_role_cannot(as_app: Connection, sql: str) -> None:
    with pytest.raises(DBAPIError) as raised, as_app.begin():
        as_app.execute(text(sql))

    assert isinstance(raised.value.orig, psycopg.errors.InsufficientPrivilege)


def test_the_app_role_can_read_insert_and_change_status(as_app: Connection) -> None:
    with as_app.begin():
        assert as_app.execute(text("SELECT count(*) FROM readings")).scalar_one() == 1
        as_app.execute(
            text(
                "INSERT INTO readings (id, meter_id, recorded_at, cumulative_kwh, source,"
                " status, created_by, created_at) SELECT gen_random_uuid(), meter_id,"
                " recorded_at + interval '1 day', cumulative_kwh + 1, source, status,"
                " created_by, created_at FROM readings"
            )
        )
        as_app.execute(
            text("UPDATE readings SET status = 'flagged', status_changed_at = now()")
        )
        statuses = as_app.execute(
            text("SELECT DISTINCT status FROM readings")
        ).scalars()
        assert list(statuses) == ["flagged"]


def test_every_granted_column_update_succeeds(as_app: Connection) -> None:
    with as_app.begin():
        granted = as_app.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.column_privileges"
                " WHERE grantee = :role AND privilege_type = 'UPDATE'"
                " AND table_schema = 'public' ORDER BY table_name, column_name"
            ),
            {"role": APP_ROLE},
        ).all()
    assert ("readings", "status") in granted
    assert ("readings", "cumulative_kwh") not in granted

    for table, column in granted:
        with as_app.begin():
            as_app.execute(text(f"UPDATE {table} SET {column} = {column} WHERE false"))


def test_downgrade_base_leaves_the_app_role_no_privilege(migrated: Scratch) -> None:
    migrate(migrated.migrator_dsn, "base", down=True)

    engine = create_engine(migrated.migrator_dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            table_grants = connection.execute(
                text(
                    "SELECT c.relname, a.privilege_type FROM pg_class c,"
                    " aclexplode(c.relacl) a WHERE c.relnamespace = 'public'::regnamespace"
                    " AND a.grantee = :role ::regrole"
                ),
                {"role": APP_ROLE},
            ).all()
            column_grants = connection.execute(
                text(
                    "SELECT c.relname, t.attname FROM pg_attribute t"
                    " JOIN pg_class c ON c.oid = t.attrelid, aclexplode(t.attacl) a"
                    " WHERE c.relnamespace = 'public'::regnamespace"
                    " AND a.grantee = :role ::regrole"
                ),
                {"role": APP_ROLE},
            ).all()
            remaining = connection.execute(
                text(
                    "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace"
                    " AND relkind = 'r'"
                )
            ).scalars()
            reads = {
                table: connection.execute(
                    text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                    {"role": APP_ROLE, "table": f"public.{table}"},
                ).scalar_one()
                for table in list(remaining)
            }
    finally:
        engine.dispose()

    assert table_grants == []
    assert column_grants == []
    assert reads == {"alembic_version": False}
