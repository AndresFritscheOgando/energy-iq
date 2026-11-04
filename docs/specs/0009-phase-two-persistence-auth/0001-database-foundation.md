# 0009/0001. Database foundation (P2-02)

## Summary

This child adds the local PostgreSQL 18 database in Docker Compose, the SQLAlchemy mappings, and the first Alembic migration with the core tables and their constraints. It also adds a readiness check and the test fixtures every later child uses. Two database roles keep the app from changing the schema or deleting rows. Nothing here exposes user data yet; P2-03 adds accounts and routes.

## Requirements

**User stories**:
- As a developer, I want one command to start a database and one to migrate it, so local setup takes minutes.
- As an operator, I want a readiness check that says whether the app can reach a migrated database.

**Acceptance criteria**:
- **AC-1**: `docker compose -f infra/compose.yaml up -d db` starts `postgres:18.<minor>-alpine` (exact tag pinned after checking the official image), bound to `127.0.0.1:5432` only, with a named volume and a `pg_isready` healthcheck. `infra/db/init/01-roles.sh` creates roles `energyiq_migrator` (LOGIN, CREATEDB, owns the databases) and `energyiq_app` (LOGIN only), and databases `energyiq_dev` and `energyiq_test`. The init script grants no table privileges: default privileges are per database and init scripts run only on a fresh volume, so **every Alembic revision carries its own `GRANT` statements** to `energyiq_app` and revokes them in `downgrade()`. That way scratch and rebuilt databases get the same grants. Revision `0001` grants: `SELECT, INSERT` on all its tables; `UPDATE (nickname, region, timezone, updated_at, archived_at)` on `properties`; `UPDATE (label, register_digits, active, deactivated_at, updated_at)` on `meters`; `UPDATE (status, status_changed_at)` on `readings`; `UPDATE (status, decided_by, decided_at)` on `meter_events`; no UPDATE on `users` except `(password_hash, disabled_at)`; none on `audit_events`; `USAGE` on the identity sequences. Never `DELETE`, `TRUNCATE`, or DDL. Passwords come from `infra/.env` (gitignored); `infra/.env.example` holds synthetic local values matching the `dev`/`test` setting defaults.
- **AC-2**: `uv run alembic upgrade head` (with `alembic.ini` at the repo root, `script_location = backend/alembic`) uses `ENERGYIQ_MIGRATION_DATABASE_URL` and creates revision `0001` (`0001_core_schema`) with exactly the tables `users`, `properties`, `meters`, `meter_events`, `readings`, `audit_events` as specified in the data model below, every constraint named per the umbrella convention. `uv run alembic downgrade base` removes all of them. Migrations are hand reviewed, never applied straight from autogenerate output.
- **AC-3**: The ORM models (SQLAlchemy 2 typed `Mapped[...]` declarative, strict Pyright clean) match the migration: `alembic check` reports no differences against `Base.metadata` after `upgrade head`. Because `alembic check` ignores CHECK constraints and expression indexes, a catalog test also queries `pg_constraint` and `pg_indexes` and asserts the exact set of expected constraint and index names (including the partial unique indexes and every `ck_*`), and the grants via `information_schema.column_privileges`.
- **AC-4**: The database enforces: `cumulative_kwh` is `NUMERIC(18,6)` and `>= 0`; every enumeration column accepts only its listed values; `users.email` is unique (the app normalizes it; there is no database lowercase CHECK, because PostgreSQL `lower()` under the database collation can disagree with Python's for some characters); properties' nickname is unique per owner among non archived rows, case insensitively; meters' label is unique per property among active rows, case insensitively; `active = (deactivated_at IS NULL)`; `register_digits` is NULL or 4 to 9; a reading is unique per `(meter_id, recorded_at)` among non voided rows; an event's `decided_by` and `decided_at` are both NULL exactly when `status = 'pending'`; every foreign key is `ON DELETE RESTRICT` and has an index. A test inserts a violating row for each rule and asserts the named constraint.
- **AC-5**: `GET /health/ready` (public, unversioned) returns 200 `{"status": "ready", "schema_revision": "<head>"}` when `SELECT version_num FROM alembic_version` equals the Alembic script head; 503 `schema_out_of_date` when it differs or the table is missing; 503 `database_unavailable` when the connection fails or exceeds a 2 second timeout (readiness uses `connect_timeout=2`, a 2 second pool checkout timeout, and `SET LOCAL statement_timeout = 2000`). `GET /health` stays dependency free (0008 AC-1).
- **AC-6**: `create_app()` succeeds with no database running; the engine connects lazily and is disposed in the app lifespan at shutdown. Each connection sets `timezone=UTC` and `statement_timeout` from settings. Any `sqlalchemy.exc.OperationalError` or pool `TimeoutError` raised in a route returns 503 `database_unavailable` with the problem shape, `X-Request-ID`, and one log line with the request id and no DSN or SQL parameters.
- **AC-7**: Test fixtures: a session scoped fixture checks the test database; if unreachable, every test marked `db` is skipped with `PostgreSQL not reachable at <host:port/db>`, or fails when `ENERGYIQ_REQUIRE_DB=1`. It runs `alembic upgrade head` once per session as the migrator. Each `db` test gets a connection inside an outer transaction and a `Session(bind=conn, join_transaction_mode="create_savepoint")`, overridden into `get_db_session`, rolled back at teardown, so tests never see each other's rows. The `db` marker is registered in `pyproject.toml`.
- **AC-8**: Settings gain the umbrella's database fields; `env=prod` without `ENERGYIQ_DATABASE_URL`, `ENERGYIQ_MIGRATION_DATABASE_URL`, or `ENERGYIQ_SECRET_KEY` fails `create_app` naming the field. DSNs are `SecretStr` and never appear in logs, problem bodies, or `repr(settings)`.
- **AC-9**: README documents compose up, migrate, run, and test with and without a database; `docs/03-TECH-STACK.md` records the pinned versions.

## Decision

Compose PostgreSQL 18 with a migrator role and an app role, SQLAlchemy 2 sync over psycopg 3, one hand reviewed Alembic revision for the core schema, a lazy engine, and savepoint isolated test sessions.

Short rationale: see the umbrella [rationale](rationale.md) (two roles, TEXT plus CHECK, app generated UUIDv4, Compose test database).

## Feature design

**Data model** (revision `0001`; `timestamptz` for every instant, `text` with length CHECKs instead of `varchar`, all columns NOT NULL unless marked null):

| Table | Columns | Constraints and indexes |
|---|---|---|
| `users` | `id uuid` · `email text` (≤ 254) · `password_hash text` · `created_at` · `disabled_at` null | `pk_users`; `uq_users_email` |
| `properties` | `id uuid` · `owner_user_id uuid` · `nickname text` (1 to 80) · `region text` null (≤ 80) · `timezone text` (1 to 64, default `'America/Santo_Domingo'`) · `created_at` · `updated_at` · `archived_at` null | `fk_properties_owner_user_id_users`; `ix_properties_owner_user_id`; partial unique `uq_properties_owner_nickname_active` on `(owner_user_id, lower(nickname)) WHERE archived_at IS NULL` |
| `meters` | `id uuid` · `property_id uuid` · `distributor text` CHECK in (`EDESUR`, `EDEESTE`, `EDENORTE`, `OTHER`) · `label text` (1 to 60) · `register_digits smallint` null CHECK 4 to 9 · `active boolean` · `deactivated_at` null · `created_at` · `updated_at` | FK and `ix_meters_property_id`; `ck_meters_active_deactivated`; partial unique `uq_meters_property_label_active` on `(property_id, lower(label)) WHERE active` |
| `meter_events` | `id uuid` · `meter_id uuid` · `event_type text` CHECK in (`installed`, `reset`, `replaced`, `rollover`, `calibration`) · `effective_at` · `status text` CHECK in (`pending`, `approved`, `rejected`) · `note text` null (≤ 500) · `created_by uuid` · `created_at` · `decided_by uuid` null · `decided_at` null | FKs to `meters` and `users` (both user FKs indexed); `ck_meter_events_decision_pair`; `ix_meter_events_meter_effective` on `(meter_id, effective_at, id)` |
| `readings` | `id uuid` · `meter_id uuid` · `recorded_at` · `original_local_date date` null · `cumulative_kwh numeric(18,6)` CHECK ≥ 0 · `source text` CHECK in (`manual`, `import`) · `status text` CHECK in (`valid`, `flagged`, `voided`) · `created_by uuid` · `created_at` · `status_changed_at` null | FKs indexed; partial unique `uq_readings_meter_instant_active` on `(meter_id, recorded_at) WHERE status <> 'voided'`; `ix_readings_meter_recorded` on `(meter_id, recorded_at, id)` |
| `audit_events` | `id bigint` identity · `actor_user_id uuid` null · `action text` · `entity_type text` · `entity_id uuid` null · `occurred_at` · `request_id text` · `metadata jsonb` default `'{}'` | FK `actor_user_id` (indexed); `ix_audit_events_entity` on `(entity_type, entity_id)` |

Revision `0002` (child 0002) adds `sessions` and `auth_attempts`; revision `0003` (child 0003) adds `idempotency_keys`. Their columns are defined in those children.

Server defaults exist only for `timezone`, `active` (`true`), and `metadata`. `created_at` and `updated_at` are always set by the app from the injected clock (`platform.clock.get_now`), so tests stay deterministic.

**State transitions**: none in this child (meter and event lifecycles arrive in 0002 and 0003).

**API surface**:
| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/health/ready` | GET | none | `status`, `schema_revision` | public | 503 `database_unavailable`, 503 `schema_out_of_date` |

**Value sourcing**:
| Action | Value | Source |
|---|---|---|
| readiness | `schema_revision` | `alembic_version.version_num` |
| readiness | expected head | `alembic.script.ScriptDirectory.from_config(...).get_current_head()`, computed once in `create_app` |
| engine | DSN, pool size, timeout | `Settings.database_url`, `db_pool_size`, `db_statement_timeout_ms` |
| migrations | DSN | `Settings.migration_database_url`, read in `backend/alembic/env.py` |
| test skip reason | host, port, db | parsed from the test DSN with the password removed |

**Key invariants**:
- The app role can never delete, truncate, alter, or update a column outside its grant list (tested in child 0004).
- Every constraint has a stable name, so `IntegrityError` maps to a problem code by name.
- psycopg returns `NUMERIC` as `Decimal` and `timestamptz` as aware UTC datetimes; the row mapping converts with `.astimezone(UTC)` before any domain call. No float ever touches kWh.
- `energyiq.readings` imports no persistence module.

**Security model**: no user facing data routes yet. The database listens on loopback only. Credentials live in the gitignored `infra/.env` and in `SecretStr` settings. Readiness reveals only the revision id.

**Configuration required**: the umbrella's `ENERGYIQ_DATABASE_URL`, `ENERGYIQ_MIGRATION_DATABASE_URL`, `ENERGYIQ_DB_POOL_SIZE`, `ENERGYIQ_DB_STATEMENT_TIMEOUT_MS`, `ENERGYIQ_SECRET_KEY`; `infra/.env` with `POSTGRES_PASSWORD`, `ENERGYIQ_MIGRATOR_PASSWORD`, `ENERGYIQ_APP_PASSWORD`.

**Critical test scenarios**:
- Fresh Compose volume → init script → `upgrade head` → `alembic check` clean, verifies **AC-1**, **AC-2**, **AC-3**
- One violating insert per constraint returns the named constraint, verifies **AC-4**
- Readiness: migrated → 200; after `downgrade base` → 503 `schema_out_of_date`; pointed at a closed port → 503 `database_unavailable` within about 2 s, verifies **AC-5**
- `create_app()` and `GET /health` with no database pass; a route forced to raise `OperationalError` returns 503 without the DSN in the log, verifies **AC-6**, **AC-8**
- Two `db` tests insert the same unique email and both pass (rollback isolation); with the database stopped, the run reports skips, and with `ENERGYIQ_REQUIRE_DB=1`, failures, verifies **AC-7**

## Build plan

1. Check the official docs for SQLAlchemy 2.x, Alembic, psycopg 3, and the `postgres` image for Python 3.13 and Windows wheels; add `sqlalchemy`, `alembic`, `psycopg[binary]`, `tzdata`, and pin them, satisfies **AC-9**
2. Thin thread: `infra/compose.yaml`, init script, `.env.example`, settings fields, `platform/db.py` with the lazy engine, an empty Alembic revision `0001`, and `/health/ready` passing against the real database, satisfies **AC-1**, **AC-5**, **AC-6**, **AC-8**
3. ORM models and the full `0001` migration with every named constraint and FK index; `alembic check` clean, satisfies **AC-2**, **AC-3**, **AC-4**
4. Test fixtures (`db` marker, skip or require, session migrate, savepoint sessions, `get_db_session` override) and the constraint tests, satisfies **AC-4**, **AC-7**
5. 503 mapping for operational errors in the problem handlers, satisfies **AC-6**
6. README and tech stack docs, satisfies **AC-9**
