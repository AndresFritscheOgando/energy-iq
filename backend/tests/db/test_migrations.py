"""Migration round trips on throwaway databases (spec 0009/0004 AC-6). Synthetic data.

Every test gets its own scratch database (``energyiq_migr_`` plus 8 hex
characters), created and dropped by the migrator even on failure.
"""

import ast
from pathlib import Path

import pytest
from alembic import command
from alembic.script import Script, ScriptDirectory
from dbsupport import CSRF, PASSWORD, Scratch, current_revision, migrate
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from energyiq.main import create_app
from energyiq.platform.db import alembic_config, script_head


def _revisions() -> list[Script]:
    """Every revision, base first."""
    return list(
        reversed(list(ScriptDirectory.from_config(alembic_config()).walk_revisions()))
    )


def _public_objects(dsn: str) -> dict[str, list[str]]:
    engine = create_engine(dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            relations = connection.execute(
                text(
                    "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace"
                    " AND relkind IN ('r', 'p', 'v', 'm', 'S', 'f') ORDER BY relname"
                )
            ).scalars()
            types = connection.execute(
                text(
                    "SELECT typname FROM pg_type WHERE typnamespace = 'public'::regnamespace"
                    " AND typtype IN ('e', 'd', 'r') ORDER BY typname"
                )
            ).scalars()
            functions = connection.execute(
                text(
                    "SELECT proname FROM pg_proc WHERE pronamespace = 'public'::regnamespace"
                    " ORDER BY proname"
                )
            ).scalars()
            return {
                "relations": list(relations),
                "types": list(types),
                "functions": list(functions),
            }
    finally:
        engine.dispose()


def test_every_revision_defines_a_non_empty_downgrade() -> None:
    revisions = _revisions()
    assert revisions

    for script in revisions:
        tree = ast.parse(Path(script.path).read_text(encoding="utf-8"))
        downgrades = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
        ]
        assert len(downgrades) == 1, script.revision
        body = [
            statement
            for statement in downgrades[0].body
            if not (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
            )
            and not isinstance(statement, ast.Pass)
        ]
        assert body, f"revision {script.revision} has an empty downgrade()"


@pytest.mark.db
def test_upgrade_downgrade_upgrade(scratch: Scratch) -> None:
    migrate(scratch.migrator_dsn, "head")
    assert current_revision(scratch.migrator_dsn) == script_head()
    migrate(scratch.migrator_dsn, "base", down=True)
    assert current_revision(scratch.migrator_dsn) is None
    migrate(scratch.migrator_dsn, "head")
    assert current_revision(scratch.migrator_dsn) == script_head()


@pytest.mark.db
def test_step_through_every_revision(scratch: Scratch) -> None:
    revisions = _revisions()

    for script in revisions:
        migrate(scratch.migrator_dsn, "+1")
        assert current_revision(scratch.migrator_dsn) == script.revision
    assert revisions[-1].revision == script_head()
    for script in reversed(revisions):
        migrate(scratch.migrator_dsn, "-1", down=True)
        assert current_revision(scratch.migrator_dsn) == script.down_revision


@pytest.mark.db
def test_downgrade_base_leaves_only_the_version_table(scratch: Scratch) -> None:
    migrate(scratch.migrator_dsn, "head")
    migrate(scratch.migrator_dsn, "base", down=True)

    assert _public_objects(scratch.migrator_dsn) == {
        "relations": ["alembic_version"],
        "types": [],
        "functions": [],
    }


@pytest.mark.db
def test_alembic_check_is_clean_at_head(scratch: Scratch) -> None:
    migrate(scratch.migrator_dsn, "head")
    engine = create_engine(scratch.migrator_dsn, poolclass=NullPool)
    config = alembic_config()
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.check(config)  # raises when the models and schema differ
    finally:
        engine.dispose()


def _seed_readings(scratch: Scratch) -> list[tuple[object, ...]]:
    """Store readings (and a retry key) through the real app; return them."""
    with TestClient(create_app(scratch.settings), headers=CSRF) as client:
        assert (
            client.post(
                "/api/v1/auth/register",
                json={"email": "migrate@example.test", "password": PASSWORD},
            ).status_code
            == 201
        )
        home = client.post("/api/v1/properties", json={"nickname": "Casa"}).json()
        meter = client.post(
            f"/api/v1/properties/{home['id']}/meters",
            json={"distributor": "EDESUR", "label": "Main"},
        ).json()
        for day, kwh in (("01", "100.5"), ("02", "110.25")):
            response = client.post(
                f"/api/v1/meters/{meter['id']}/readings",
                json={"recorded_at": f"2026-10-{day}T12:00:00Z", "cumulative_kwh": kwh},
                headers={"Idempotency-Key": f"seed-{day}"},
            )
            assert response.status_code == 201, response.text
    return _readings(scratch.migrator_dsn)


def _readings(dsn: str) -> list[tuple[object, ...]]:
    engine = create_engine(dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return [
                tuple(row)
                for row in connection.execute(
                    text("SELECT * FROM readings ORDER BY recorded_at, id")
                )
            ]
    finally:
        engine.dispose()


@pytest.mark.db
def test_downgrade_0003_to_0002_keeps_the_readings(scratch: Scratch) -> None:
    migrate(scratch.migrator_dsn, "head")
    assert script_head() == "0004"
    before = _seed_readings(scratch)
    assert len(before) == 2

    migrate(scratch.migrator_dsn, "0002", down=True)

    assert current_revision(scratch.migrator_dsn) == "0002"
    assert "idempotency_keys" not in _public_objects(scratch.migrator_dsn)["relations"]
    assert _readings(scratch.migrator_dsn) == before
    migrate(scratch.migrator_dsn, "head")
    assert _readings(scratch.migrator_dsn) == before
