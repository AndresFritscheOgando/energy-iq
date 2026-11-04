"""Purge expired security rows (spec 0009/0002 AC-11).

Run with ``uv run python -m energyiq.platform.maintenance``. It connects with
``ENERGYIQ_MIGRATION_DATABASE_URL`` (the app role cannot delete) and, in one
transaction, deletes:

- ``auth_attempts`` older than 24 hours;
- ``sessions`` whose ``expires_at`` or ``revoked_at`` is more than 30 days past;
- ``idempotency_keys`` past ``expires_at``, once child 0003 adds that table.

It prints one count per table, never row contents, and exits 0. Invalid or
missing settings exit 2 naming the fields. Nothing schedules it yet (P8).
"""

import sys
from collections.abc import Sequence
from datetime import datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.pool import NullPool

from energyiq.platform.clock import get_now
from energyiq.platform.db import connect_args
from energyiq.platform.settings import Settings

ATTEMPT_RETENTION = timedelta(hours=24)
SESSION_RETENTION = timedelta(days=30)

EXIT_OK = 0
EXIT_CONFIG = 2


def _delete(connection: Connection, sql: str, cutoff: datetime) -> int:
    return connection.execute(text(sql), {"cutoff": cutoff}).rowcount


def purge(engine: Engine, now: datetime) -> dict[str, int]:
    """Delete expired rows in one transaction; returns deleted counts."""
    counts: dict[str, int] = {}
    with engine.begin() as connection:
        counts["auth_attempts"] = _delete(
            connection,
            "DELETE FROM auth_attempts WHERE attempted_at < :cutoff",
            now - ATTEMPT_RETENTION,
        )
        counts["sessions"] = _delete(
            connection,
            "DELETE FROM sessions WHERE expires_at < :cutoff OR revoked_at < :cutoff",
            now - SESSION_RETENTION,
        )
        has_keys = connection.execute(
            text("SELECT to_regclass('public.idempotency_keys') IS NOT NULL")
        ).scalar_one()
        if has_keys:
            counts["idempotency_keys"] = _delete(
                connection,
                "DELETE FROM idempotency_keys WHERE expires_at < :cutoff",
                now,
            )
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    del argv  # no options yet
    try:
        settings = Settings()
    except ValidationError as exc:
        fields = sorted({".".join(map(str, error["loc"])) for error in exc.errors()})
        print(f"invalid settings: {', '.join(fields)}", file=sys.stderr)
        return EXIT_CONFIG
    engine = create_engine(
        settings.migration_database_url.get_secret_value(),
        poolclass=NullPool,
        hide_parameters=True,
        connect_args=connect_args(settings.db_statement_timeout_ms),
    )
    try:
        counts = purge(engine, get_now())
    finally:
        engine.dispose()
    for table, count in counts.items():
        print(f"{table}: {count}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
