"""Find orphan and missing document files (spec 0012/0002 AC-4).

Run with ``uv run python -m energyiq.documents.reconcile [--fix]``. It reports:

- ``orphan_files``: a stored file no document row names, older than the grace
  period (a younger one may be an upload that has renamed its file but not yet
  committed);
- ``missing_files``: a live document whose file is gone (the worker fails its
  run with ``source_missing``);
- ``unpurged_tombstones``: a deleted document whose file removal was not
  recorded, because the process stopped after the tombstone committed;
- ``stale_temp_files``: leftover ``tmp/*.part`` files older than the grace period.

Without ``--fix`` it only reports. With ``--fix`` it removes orphans, stale
temporary files, and the files of tombstones, and records ``purged_at``. It
prints counts and opaque storage keys, never file contents or owner data, and
exits 0, or 1 when it found something it did not fix.
"""

import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from energyiq.documents.models import SourceDocumentRow
from energyiq.documents.storage import DocumentStore, LocalDocumentStore
from energyiq.platform.clock import get_now
from energyiq.platform.db import build_engine, session_factory
from energyiq.platform.settings import Settings

GRACE_SECONDS = 300
EXIT_OK = 0
EXIT_FOUND = 1
EXIT_CONFIG = 2


@dataclass
class Report:
    orphan_files: list[UUID] = field(default_factory=list[UUID])
    missing_files: list[UUID] = field(default_factory=list[UUID])
    unpurged_tombstones: list[UUID] = field(default_factory=list[UUID])
    stale_temp_files: int = 0
    fixed: bool = False

    @property
    def clean(self) -> bool:
        return not (
            self.orphan_files
            or self.missing_files
            or self.unpurged_tombstones
            or self.stale_temp_files
        )


def reconcile(
    factory: sessionmaker[Session],
    store: DocumentStore,
    now: datetime,
    *,
    fix: bool = False,
    grace_seconds: float = GRACE_SECONDS,
    clock_seconds: float | None = None,
) -> Report:
    """Compare the document rows with the files; optionally repair."""
    report = Report(fixed=fix)
    cutoff = (time.time() if clock_seconds is None else clock_seconds) - grace_seconds
    with factory() as session, session.begin():
        rows = session.execute(
            select(
                SourceDocumentRow.id,
                SourceDocumentRow.storage_key,
                SourceDocumentRow.deleted_at,
                SourceDocumentRow.purged_at,
            )
        ).all()
        known = {row.storage_key for row in rows}
        for key in sorted(store.keys(), key=str):
            if key in known:
                continue
            path = store.open_path(key)
            if path.stat().st_mtime > cutoff:
                continue
            report.orphan_files.append(key)
            if fix:
                store.delete(key)
        for row in rows:
            present = store.exists(row.storage_key)
            if row.deleted_at is None and not present:
                report.missing_files.append(row.id)
            if row.deleted_at is not None and row.purged_at is None:
                report.unpurged_tombstones.append(row.id)
                if fix:
                    if present:
                        store.delete(row.storage_key)
                    session.execute(
                        update(SourceDocumentRow)
                        .where(SourceDocumentRow.id == row.id)
                        .values(purged_at=now)
                        .execution_options(synchronize_session=False)
                    )
        for path in store.temp_files():
            if path.stat().st_mtime <= cutoff:
                report.stale_temp_files += 1
                if fix:
                    store.discard(path)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    fix = "--fix" in arguments
    try:
        settings = Settings()
    except ValidationError as exc:
        fields = sorted({".".join(map(str, error["loc"])) for error in exc.errors()})
        print(f"invalid settings: {', '.join(fields)}", file=sys.stderr)
        return EXIT_CONFIG
    engine = build_engine(settings)
    try:
        report = reconcile(
            session_factory(engine),
            LocalDocumentStore(settings.document_root),
            get_now(),
            fix=fix,
        )
    finally:
        engine.dispose()
    for name in ("orphan_files", "missing_files", "unpurged_tombstones"):
        values: list[UUID] = getattr(report, name)
        print(f"{name}: {len(values)}")
        for value in values:
            print(f"  {value}")
    print(f"stale_temp_files: {report.stale_temp_files}")
    print("repaired" if fix else "report only")
    if report.clean or fix and not report.missing_files:
        return EXIT_OK
    return EXIT_FOUND


if __name__ == "__main__":
    raise SystemExit(main())
