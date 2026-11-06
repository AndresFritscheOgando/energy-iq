"""Tariff publication, immutability, and privileges (spec 0012/0006 AC-1, AC-2).

Synthetic rules only (see ``tariffsupport``). These commit to the test database;
``committed_db`` truncates before and after.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from tariffsupport import SOURCE_DIGEST, schedule_dict, write_manifest, write_source

from energyiq.tariffs import publish, repository
from energyiq.tariffs.domain import TariffSchedule
from energyiq.tariffs.manifest import load_manifest

pytestmark = pytest.mark.db_commit

NOW = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)


def _run(
    engine: Engine, directory: Path, schedules: list[dict[str, Any]], *, go: bool
) -> tuple[int, list[str]]:
    manifest = load_manifest(write_manifest(directory, schedules))
    return publish.apply_manifest(engine, manifest, publish=go, now=NOW)


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_dry_run_writes_nothing(
    committed_db: Engine, migrator_engine: Engine, tmp_path: Path
) -> None:
    code, lines = _run(migrator_engine, tmp_path, [schedule_dict()], go=False)
    assert code == 0
    assert lines[0].startswith("would publish: SIE-900-2026-TF EDESUR BTS-1")
    assert _count(migrator_engine, "tariff_schedules") == 0
    assert _count(migrator_engine, "audit_events") == 0


def test_publish_stores_rule_bands_and_a_system_audit_row(
    committed_db: Engine, migrator_engine: Engine, tmp_path: Path
) -> None:
    code, lines = _run(migrator_engine, tmp_path, [schedule_dict()], go=True)
    assert (code, lines[0].split(":")[0]) == (0, "published")
    assert _count(migrator_engine, "tariff_schedules") == 1
    assert _count(migrator_engine, "tariff_bands") == 6
    with migrator_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT actor_user_id, action, entity_type, request_id, metadata"
                " FROM audit_events"
            )
        ).one()
        version, manifest_revision = connection.execute(
            text("SELECT version, manifest_revision FROM tariff_schedules")
        ).one()
    assert row.actor_user_id is None
    assert (row.action, row.entity_type, row.request_id) == (
        "tariff.publish",
        "tariff_schedule",
        "maintenance",
    )
    assert row.metadata == {
        "manifest_revision": "synthetic-1",
        "resolution_id": "SIE-900-2026-TF",
        "source_digest": SOURCE_DIGEST,
    }
    assert "1.00" not in str(row.metadata)  # no rate in the audit trail
    assert (version, manifest_revision) == (1, "synthetic-1")


def test_stored_rule_round_trips_to_the_same_schedule(
    committed_db: Engine, migrator_engine: Engine, tmp_path: Path
) -> None:
    _run(migrator_engine, tmp_path, [schedule_dict()], go=True)
    from sqlalchemy.orm import Session

    with Session(migrator_engine) as session:
        found = repository.schedules_overlapping(
            session,
            "EDESUR",
            "BTS-1",
            datetime(2026, 10, 1).date(),
            datetime(2026, 10, 2).date(),
        )
    assert found == [TariffSchedule.model_validate(schedule_dict())]


def test_publishing_the_same_rule_again_changes_nothing(
    committed_db: Engine, migrator_engine: Engine, tmp_path: Path
) -> None:
    _run(migrator_engine, tmp_path, [schedule_dict()], go=True)
    code, lines = _run(migrator_engine, tmp_path, [schedule_dict()], go=True)
    assert code == 0 and lines[0].startswith("already published")
    assert _count(migrator_engine, "tariff_schedules") == 1
    assert _count(migrator_engine, "audit_events") == 1


def test_a_different_rule_for_a_published_resolution_is_refused(
    committed_db: Engine, migrator_engine: Engine, tmp_path: Path
) -> None:
    _run(migrator_engine, tmp_path, [schedule_dict()], go=True)
    changed = schedule_dict(rounding={"places": 3, "mode": "half_up", "scope": "total"})
    code, lines = _run(migrator_engine, tmp_path, [changed], go=True)
    assert code == 1 and lines[0].startswith("REFUSED: differs from published")
    with migrator_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT rounding_places FROM tariff_schedules")
            ).scalar_one()
            == 2
        )


def test_overlap_with_another_published_rule_is_refused_all_or_nothing(
    committed_db: Engine, migrator_engine: Engine, tmp_path: Path
) -> None:
    _run(migrator_engine, tmp_path, [schedule_dict()], go=True)
    clash = schedule_dict(
        resolution_id="SIE-901-2026-TF",
        effective_start="2026-12-01",
        effective_end="2027-03-31",
    )
    fine = schedule_dict(resolution_id="SIE-902-2026-TF", distributor="EDENORTE")
    code, lines = _run(migrator_engine, tmp_path, [fine, clash], go=True)
    assert code == 1
    assert any(line.startswith("REFUSED: overlaps") for line in lines)
    assert any(line.startswith("NOT published") for line in lines)
    assert (
        _count(migrator_engine, "tariff_schedules") == 1
    )  # even the fine one rolled back
    assert _count(migrator_engine, "audit_events") == 1


def test_a_new_resolution_after_the_old_dates_is_version_two(
    committed_db: Engine, migrator_engine: Engine, tmp_path: Path
) -> None:
    _run(migrator_engine, tmp_path, [schedule_dict()], go=True)
    later = schedule_dict(
        resolution_id="SIE-910-2027-TF",
        effective_start="2027-01-01",
        effective_end="2027-03-31",
    )
    code, _ = _run(migrator_engine, tmp_path, [later], go=True)
    assert code == 0
    with migrator_engine.connect() as connection:
        versions = connection.execute(
            text("SELECT resolution_id, version FROM tariff_schedules ORDER BY version")
        ).all()
    assert [tuple(row) for row in versions] == [
        ("SIE-900-2026-TF", 1),
        ("SIE-910-2027-TF", 2),
    ]


def test_database_exclusion_blocks_overlap_even_without_the_command(
    committed_db: Engine, migrator_engine: Engine, tmp_path: Path
) -> None:
    _run(migrator_engine, tmp_path, [schedule_dict()], go=True)
    with (
        pytest.raises(IntegrityError, match="ex_tariff_schedules_overlap"),
        migrator_engine.begin() as connection,
    ):
        connection.execute(
            text(
                "INSERT INTO tariff_schedules (id, distributor, tariff_class, version,"
                " effective_start, effective_end, resolution_id, source_url, source_digest,"
                " published_on, checked_on, checked_by, rounding_places, rounding_mode,"
                " rounding_scope, manifest_revision, published_at)"
                " SELECT gen_random_uuid(), distributor, tariff_class, 2,"
                " effective_start, effective_end, 'SIE-999-2026-TF', source_url, source_digest,"
                " published_on, checked_on, checked_by, rounding_places, rounding_mode,"
                " rounding_scope, manifest_revision, published_at FROM tariff_schedules"
            )
        )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE tariff_schedules SET checked_by = 'someone else'",
        "DELETE FROM tariff_schedules",
        "UPDATE tariff_bands SET amount = 99",
        "DELETE FROM tariff_bands",
    ],
)
def test_published_rows_are_immutable_even_for_the_migrator(
    committed_db: Engine, migrator_engine: Engine, tmp_path: Path, statement: str
) -> None:
    _run(migrator_engine, tmp_path, [schedule_dict()], go=True)
    with (
        pytest.raises((IntegrityError, DBAPIError), match="immutable"),
        migrator_engine.begin() as connection,
    ):
        connection.execute(text(statement))
    assert _count(migrator_engine, "tariff_bands") == 6


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO tariff_schedules (id) VALUES (gen_random_uuid())",
        "UPDATE tariff_schedules SET checked_by = 'x'",
        "DELETE FROM tariff_bands",
        "INSERT INTO tariff_bands (id) VALUES (gen_random_uuid())",
    ],
)
def test_app_role_cannot_write_tariffs(
    committed_db: Engine, migrator_engine: Engine, tmp_path: Path, statement: str
) -> None:
    _run(migrator_engine, tmp_path, [schedule_dict()], go=True)
    with (
        pytest.raises(ProgrammingError, match="permission denied"),
        committed_db.begin() as connection,
    ):
        connection.execute(text(statement))
    with committed_db.connect() as connection:  # but it can read
        assert (
            connection.execute(
                text("SELECT count(*) FROM tariff_schedules")
            ).scalar_one()
            == 1
        )


def test_main_refuses_a_manifest_whose_source_does_not_match(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = write_manifest(tmp_path)
    wrong = tmp_path / "wrong.bin"
    wrong.write_bytes(b"another file")
    assert publish.main([str(manifest), "--source-file", str(wrong)]) == 2
    assert "no source file matches" in capsys.readouterr().err
    assert publish.main([str(manifest)]) == 2  # no source at all
    assert write_source(tmp_path).exists()


def test_command_publishes_in_a_fresh_process(
    committed_db: Engine, migrator_engine: Engine, tmp_path: Path
) -> None:
    """The module run as a command loads only what it imports, unlike this suite."""
    import os
    import subprocess
    import sys

    manifest = write_manifest(tmp_path)
    source = write_source(tmp_path)
    env = {
        **os.environ,
        "ENERGYIQ_ENV": "test",
        "PYTHONPATH": str(Path(publish.__file__).parents[2]),
    }
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "energyiq.tariffs.publish",
            str(manifest),
            "--source-file",
            str(source),
            "--publish",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-800:]
    assert done.stdout.startswith("published: SIE-900-2026-TF")
    assert _count(migrator_engine, "tariff_schedules") == 1
    assert _count(migrator_engine, "audit_events") == 1
