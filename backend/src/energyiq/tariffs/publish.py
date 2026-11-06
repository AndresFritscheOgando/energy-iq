"""Publish checked tariff rules from a manifest (spec 0012/0006 AC-1, AC-2).

Run with::

    uv run python -m energyiq.tariffs.publish MANIFEST --source-file SOURCE.pdf
    uv run python -m energyiq.tariffs.publish MANIFEST --source-file SOURCE.pdf --publish

This is an offline, trusted maintenance operation, not a route. It connects with
``ENERGYIQ_MIGRATION_DATABASE_URL`` (the app role cannot write tariffs). Code
review of the manifest and the migrator credential authorize publication.

Without ``--publish`` it only validates: manifest shape, that each source file
matches its recorded SHA-256 digest, and that no rule overlaps another published
rule for the same distributor and class. With ``--publish`` it inserts the rules
in one transaction and records one system audit row per rule holding the
manifest revision, resolution, and source digest, never a rate or private data.
Publishing the same rule twice does nothing. A published rule is immutable, so a
different rule for a resolution already published is refused. Exit codes: 0 done,
1 refused (conflict or overlap), 2 invalid manifest, source, or settings.
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from energyiq.platform.audit import record_audit
from energyiq.platform.clock import get_now
from energyiq.platform.db import connect_args
from energyiq.platform.schema import load_metadata
from energyiq.platform.settings import Settings
from energyiq.tariffs import repository
from energyiq.tariffs.domain import TariffSchedule
from energyiq.tariffs.manifest import (
    ManifestError,
    TariffManifest,
    load_manifest,
    verify_sources,
)

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_INVALID = 2
_LOCK_KEY = 0x74617269  # "tari": serializes concurrent publishers


def _label(schedule: TariffSchedule) -> str:
    return (
        f"{schedule.resolution_id} {schedule.distributor.value} {schedule.tariff_class}"
        f" {schedule.effective_start.isoformat()}..{schedule.effective_end.isoformat()}"
    )


def apply_manifest(
    engine: Engine, manifest: TariffManifest, *, publish: bool, now: datetime
) -> tuple[int, list[str]]:
    """Validate against stored rules and, when ``publish``, insert them.

    All or nothing: any refusal rolls the whole manifest back. Returns the exit
    code and one line per rule.
    """
    load_metadata()  # a bare `python -m` run imports only some models
    lines: list[str] = []
    refused = False
    with Session(engine) as session:
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY})
        for schedule in manifest.schedules:
            existing = repository.find_by_resolution(session, schedule)
            if existing is not None:
                same = existing == schedule
                prefix = (
                    "already published" if same else "REFUSED: differs from published"
                )
                lines.append(f"{prefix}: {_label(schedule)}")
                refused = refused or not same
                continue
            if repository.overlapping_published(session, schedule):
                lines.append(f"REFUSED: overlaps a published rule: {_label(schedule)}")
                refused = True
                continue
            if not publish:
                lines.append(f"would publish: {_label(schedule)}")
                continue
            schedule_id = repository.insert_published(
                session, schedule, manifest.manifest_revision, now
            )
            record_audit(
                session,
                None,
                "tariff.publish",
                "tariff_schedule",
                schedule_id,
                "maintenance",
                {
                    "manifest_revision": manifest.manifest_revision,
                    "resolution_id": schedule.resolution_id,
                    "source_digest": schedule.source_digest,
                },
                occurred_at=now,
            )
            lines.append(f"published: {_label(schedule)}")
        if refused:
            session.rollback()
            lines = [
                line.replace("published:", "NOT published:", 1)
                if line.startswith("published:")
                else line
                for line in lines
            ]
        else:
            session.commit()
    return (EXIT_REFUSED if refused else EXIT_OK), lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="energyiq.tariffs.publish")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--source-file", type=Path, action="append", default=[])
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        verify_sources(manifest, args.source_file)
    except ManifestError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return EXIT_INVALID
    try:
        settings = Settings()
    except ValidationError as exc:
        fields = sorted({".".join(map(str, error["loc"])) for error in exc.errors()})
        print(f"invalid settings: {', '.join(fields)}", file=sys.stderr)
        return EXIT_INVALID
    engine = create_engine(
        settings.migration_database_url.get_secret_value(),
        poolclass=NullPool,
        hide_parameters=True,
        connect_args=connect_args(settings.db_statement_timeout_ms),
    )
    try:
        code, lines = apply_manifest(
            engine, manifest, publish=args.publish, now=get_now()
        )
    except IntegrityError:
        print("REFUSED: the database rejected the rule", file=sys.stderr)
        return EXIT_REFUSED
    finally:
        engine.dispose()
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
