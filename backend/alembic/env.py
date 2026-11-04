"""Alembic environment (spec 0009/0001 AC-2).

Online mode only. The connection comes from, in order:

1. ``config.attributes["connection"]``, set by the test fixtures;
2. ``ENERGYIQ_MIGRATION_DATABASE_URL`` (the migrator role), through ``Settings``.

The app role never runs migrations.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine, pool

from energyiq.platform.db import connect_args
from energyiq.platform.schema import load_metadata
from energyiq.platform.settings import Settings

config = context.config
target_metadata = load_metadata()


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    given = config.attributes.get("connection")
    if isinstance(given, Connection):
        _run(given)
        return

    if config.config_file_name is not None:
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    settings = Settings()
    engine = create_engine(
        settings.migration_database_url.get_secret_value(),
        poolclass=pool.NullPool,
        connect_args=connect_args(settings.db_statement_timeout_ms),
    )
    with engine.connect() as connection:
        _run(connection)
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) migrations are not supported.")
run_migrations_online()
