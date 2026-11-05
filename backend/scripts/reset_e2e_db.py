"""Rebuild the end to end database (spec 0011 child 0003 AC-2).

Connects as the migrator to the ``postgres`` database, drops and recreates the
target with the grants of the ``scratch`` test fixture, then runs Alembic. It
can only ever touch ``energyiq_e2e``; the dev and test databases are never
named here. A new database also clears the rate limit rows.

``--print-urls`` prints the suite's app and migrator URLs as JSON and changes
nothing, so the frontend runner needs no copy of the local passwords.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from energyiq.platform.settings import local_database_url

TARGET = "energyiq_e2e"
APP_ROLE = "energyiq_app"
OBJECT_IN_USE = "55006"


def _with_database(dsn: str, database: str) -> str:
    return make_url(dsn).set(database=database).render_as_string(hide_password=False)


def _migrator_url() -> str:
    return os.environ.get("ENERGYIQ_MIGRATION_DATABASE_URL") or local_database_url(
        "test", migrator=True
    )


def suite_urls() -> dict[str, str]:
    return {
        "app": _with_database(local_database_url("test"), TARGET),
        "migrator": _with_database(_migrator_url(), TARGET),
    }


def recreate(migrator_url: str) -> None:
    admin = create_engine(
        _with_database(migrator_url, "postgres"),
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TARGET}"'))
            connection.execute(text(f'CREATE DATABASE "{TARGET}"'))
            connection.execute(text(f'REVOKE ALL ON DATABASE "{TARGET}" FROM PUBLIC'))
            connection.execute(
                text(f'GRANT CONNECT ON DATABASE "{TARGET}" TO {APP_ROLE}')
            )
    finally:
        admin.dispose()
    engine = create_engine(_with_database(migrator_url, TARGET), poolclass=NullPool)
    try:
        with engine.begin() as connection:
            connection.execute(text("REVOKE ALL ON SCHEMA public FROM PUBLIC"))
            connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))
    finally:
        engine.dispose()


def migrate(urls: dict[str, str]) -> None:
    env = {
        **os.environ,
        "ENERGYIQ_ENV": "test",
        "ENERGYIQ_DATABASE_URL": urls["app"],
        "ENERGYIQ_MIGRATION_DATABASE_URL": urls["migrator"],
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--print-urls", action="store_true")
    args = parser.parse_args(argv)

    if args.database != TARGET:
        print(f"refusing to touch {args.database!r}: only {TARGET} may be reset.")
        return 2

    urls = suite_urls()
    if args.print_urls:
        print(json.dumps(urls))
        return 0

    try:
        recreate(_migrator_url())
    except OperationalError as error:
        print(
            "can't reach the database. Start it with "
            "`docker compose --env-file infra/.env -f infra/compose.yaml up -d`, "
            f"then run this again. ({type(error).__name__})"
        )
        return 1
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) == OBJECT_IN_USE:
            print(f"stop the process using {TARGET}, then run this again.")
            return 1
        raise
    migrate(urls)
    print(f"{TARGET} is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
