# Verify: Phase 2 persistence · spec 0009 · updated 2026-11-04
_Steps come from the spec 0009 acceptance criteria. `/check verify` runs these, and `/test` can lock in the ones worth keeping. Use synthetic data only. Run the commands from the repository root in PowerShell._

## Child 0001: Database foundation (P2-02)

### Commands
- [x] `docker compose -f infra/compose.yaml down -v`, then `Copy-Item infra/.env.example infra/.env` (if missing) and `docker compose -f infra/compose.yaml up -d db` → the container reaches `healthy`; `docker logs energyiq-db-1` shows `01-roles.sh` creating two roles and two databases → AC-1
- [x] `docker port energyiq-db-1` → only `127.0.0.1:5432`; `docker inspect energyiq-db-1` shows the image `postgres:18.6-alpine` and the named volume `energyiq_energyiq-pgdata` → AC-1
- [x] `docker exec energyiq-db-1 psql -U postgres -c "\du"` → `energyiq_migrator` (Create DB) and `energyiq_app` (no attributes); `\l` → both databases are owned by `energyiq_migrator` → AC-1
- [x] Before you migrate: `docker exec energyiq-db-1 psql -U postgres -d energyiq_dev -c "\dp"` → no tables and no grants (the init script grants nothing) → AC-1
- [x] `uv run alembic upgrade head` → `Running upgrade  -> 0001`; `uv run alembic current` → `0001 (head)` → AC-2
- [x] `uv run alembic check` → `No new upgrade operations detected.` → AC-3
- [x] `uv run alembic downgrade base`, then list the public tables → only `alembic_version` is left (empty), and `energyiq_app` has no table privileges. Then run `uv run alembic upgrade head` again → AC-2, AC-1
- [x] `uv run pytest -q -p no:cacheprovider backend/tests/db/test_schema.py` → the exact constraint names, index names, partial index definitions, FKs with `ON DELETE RESTRICT` and a leading index, `NUMERIC(18,6)`, `timestamptz`, and the app role's table, column, and sequence grants all match → AC-3, AC-1
- [x] `uv run pytest -q -p no:cacheprovider backend/tests/db/test_constraints.py` → each violating insert names its constraint; the allowed edge cases pass (archived nickname reuse, inactive label reuse, voided instant reuse, digits 4, 9, and null, max kWh) → AC-4
- [x] Start the API (`uv run uvicorn energyiq.main:create_app --factory --app-dir backend/src --no-access-log`), then `Invoke-WebRequest http://127.0.0.1:8000/health/ready` → 200 `{"status":"ready","schema_revision":"0001"}` → AC-5
- [x] With the server still running, `uv run alembic downgrade base` → `/health/ready` answers 503 `schema_out_of_date` with `X-Request-ID`. Then `uv run alembic upgrade head` → 200 again → AC-5
- [x] `docker compose -f infra/compose.yaml stop db` → `/health` still answers 200; `/health/ready` answers 503 `database_unavailable` in about 2 s, and the body holds no host, role, or password. Then `docker compose -f infra/compose.yaml start db` → AC-5, AC-6
- [x] With the database stopped, start the server fresh → it starts with no error (the engine connects lazily) → AC-6
- [x] `uv run pytest -q -p no:cacheprovider backend/tests/db/test_readiness.py` → connections report `timezone=UTC` and the configured `statement_timeout`; `pg_sleep` over the timeout answers 503 with exactly one `energyiq.errors` line, `database unavailable: OperationalError`, plus the request id → AC-6
- [x] `uv run pytest -q -p no:cacheprovider backend/tests/api/test_database_platform.py` → 503 mapping for `OperationalError` and pool `TimeoutError` with no DSN, SQL, or parameters in logs or bodies; the lifespan disposes both engines → AC-6
- [x] `$env:ENERGYIQ_ENV = "prod"; uv run python -c "import sys; sys.path.insert(0, 'backend/src'); from energyiq.main import create_app; create_app()"` → `ValidationError` naming `database_url`, `migration_database_url`, and `secret_key` as `missing`. Then `Remove-Item Env:ENERGYIQ_ENV` → AC-8
- [x] `uv run python -c "import sys; sys.path.insert(0, 'backend/src'); from energyiq.platform.settings import Settings; print(repr(Settings()))"` → every secret shows as `SecretStr('**********')` → AC-8
- [x] With the database stopped: `uv run pytest -q -p no:cacheprovider` → all non `db` tests pass, and every `db` test is skipped with `PostgreSQL not reachable at 127.0.0.1:5432/energyiq_test` → AC-7
- [x] With the database stopped: `$env:ENERGYIQ_REQUIRE_DB = "1"; uv run pytest -q -p no:cacheprovider` → the `db` tests error with the same reason plus `ENERGYIQ_REQUIRE_DB=1`. Then `Remove-Item Env:ENERGYIQ_REQUIRE_DB` → AC-7
- [x] With the database running and `ENERGYIQ_REQUIRE_DB=1`: the full suite passes, `ruff check .`, `ruff format --check .`, and `pyright` are clean, and `test_rows_from_another_test_are_never_visible` passes in both runs (rollback isolation) → AC-7, umbrella AC-3
- [x] Read README "Run the database" and the quality checks note, and the database row in `docs/03-TECH-STACK.md` → the compose, migrate, run, and test steps (with and without a database) are there, with the locked versions → AC-9

### Value sourcing
- [x] `schema_revision` comes from `alembic_version.version_num`: run `docker exec energyiq-db-1 psql -U energyiq_migrator -d energyiq_dev -c "UPDATE alembic_version SET version_num = '0000'"` → readiness answers 503 `schema_out_of_date` (not 200 with `0000`). Then `UPDATE ... SET version_num = '0001'` → 200 → AC-5
- [x] The expected head comes from the script directory, computed once in `create_app`: `app.state.schema_head == "0001"` and matches `ScriptDirectory(...).get_current_head()` → AC-5
- [x] The engine DSN, pool size, and timeout come from `Settings`: start with `ENERGYIQ_DB_STATEMENT_TIMEOUT_MS=1500` → `SHOW statement_timeout` through the app session is `1500ms` → AC-6
- [x] The migration DSN comes from `ENERGYIQ_MIGRATION_DATABASE_URL`: run `uv run alembic current` with it pointed at the test database (or with `ENERGYIQ_ENV=test`) → it reports the test database's revision, not dev's → AC-2
- [x] The skip reason's host, port, and database come from the test DSN with the password removed: run with `ENERGYIQ_MIGRATION_DATABASE_URL` set to a closed port → the reason names that `host:port/db`, and the password appears nowhere in the output → AC-7

### Acceptance criteria coverage
- AC-1: Compose, roles, init script, and grants steps; catalog grant tests
- AC-2: upgrade, current, downgrade, and migration DSN steps
- AC-3: `alembic check` and catalog tests
- AC-4: constraint tests
- AC-5: readiness live, downgrade, stopped database, and value sourcing steps
- AC-6: lazy start, UTC and timeout, 503 mapping, and log content steps
- AC-7: skip, require, isolation, and skip reason steps
- AC-8: prod missing secrets and secret rendering steps
- AC-9: README and tech stack review
