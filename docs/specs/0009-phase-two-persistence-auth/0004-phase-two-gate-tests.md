# 0009/0004. Phase 2 gate tests (P2-05)

## Summary

This child proves the Phase 2 promises with tests that cover every route at once instead of one route at a time. One user can never see or change another user's data. Repeated and concurrent requests never double write. Every migration can go up and down cleanly. The app's database role cannot delete rows or change the schema. The matrices list routes from the app itself, so a new route that is not covered fails the build.

## Requirements

**User stories**:
- As the owner of this codebase, I want ownership, duplicate safety, and migrations proven by tests that grow with the API, so P3 and P7 build on a verified base.

**Acceptance criteria**:
- **AC-1**: Cross user matrix: a fixture builds users A and B, each with a property, an active meter, a reading, and a pending event, plus an archived property for A. A test enumerates every `APIRoute` in `create_app().routes` whose path contains an id parameter, and fails if any route is missing from the matrix table. For each route and method, B calling with A's ids returns 404 `not_found` whose body equals (apart from `request_id`) the body for a random UUID, and the database is unchanged (row counts per table and the latest `audit_events.id` compared before and after). A calling its archived property's id gets the same 404.
- **AC-2**: List isolation: every list route returns only the caller's rows (B's lists never contain A's ids), checked after A and B each create several rows.
- **AC-3**: Unauthenticated matrix: every `/api/v1` route except `auth/register`, `auth/login`, and `auth/logout` returns 401 `not_authenticated` with no cookie, a malformed cookie, an unknown token, a revoked session, an expired session, and a disabled user's session (route list enumerated from the app).
- **AC-4**: CSRF matrix: every unsafe method route under `/api/v1` returns 403 `csrf_rejected` without `X-EnergyIQ-CSRF`, and with `Origin: http://evil.test` (enumerated).
- **AC-5**: Duplicate requests on real PostgreSQL with committed transactions: (a) the same `Idempotency-Key` and body sent twice sequentially gives identical status and body, one row, one audit row, for every route that declares the `idempotent` dependency (enumerated from `app.routes`); (b) the same key from two threads at once gives one write and two identical responses; (c) two identical reading POSTs without a key at the same instant give one 201 and one 409 `reading_exists_at_instant`; (d) concurrent registration of one email gives one 201 and one 409 `email_taken`; (e) concurrent status changes on one reading leave a consistent final state and one audit row per real transition. Overlap is forced, never left to timing: for (b), (c), and (e) a third connection holds the contested row (the meter row via `SELECT ... FOR UPDATE`, or for (b) an uncommitted insert of the same idempotency key) while both requests start; the test waits until `pg_stat_activity` shows both blocked on a lock, then releases it. For (d), the third connection holds an uncommitted insert of the same email.
- **AC-6**: Migrations: on a fresh scratch database (created and dropped by the test as the migrator), `upgrade head` → `downgrade base` → `upgrade head` succeeds; stepping `upgrade +1` and `downgrade -1` through every revision succeeds; after `downgrade base` only `alembic_version` remains; `alembic check` is clean at head; a test asserts every revision file defines a non empty `downgrade()`. A downgrade from `0003` to `0002` with data present succeeds and keeps the readings.
- **AC-7**: Privileges, on a scratch database migrated from empty (so grants come from the revisions alone): connected as `energyiq_app`, `DELETE FROM readings`, `TRUNCATE readings`, `CREATE TABLE x ()`, `ALTER TABLE readings ...`, `UPDATE readings SET cumulative_kwh = ...`, `UPDATE readings SET recorded_at = ...`, and any `UPDATE audit_events` each fail with `InsufficientPrivilege`; `SELECT`, `INSERT`, and the granted column `UPDATE`s (for example `readings.status`) succeed. After `downgrade base`, the app role holds no privilege on any remaining table.
- **AC-8**: The gate run `ENERGYIQ_REQUIRE_DB=1 uv run pytest` passes with no skips in `db` tests; the default run without a database passes with those tests skipped; Ruff and Pyright pass. PROGRESS and the roadmap record the Phase 2 gate only with this evidence.

## Decision

Table driven matrices built from `app.routes` (coverage enforced by the test itself), committed transaction concurrency tests in a separate `db_commit` group that truncates tables between tests as the migrator, and Alembic round trips on throwaway databases.

Short rationale: enumerating routes turns "did we remember to test the new endpoint" into a failing test, and real commits are the only way to exercise unique index races and idempotency waits, which savepoint isolation hides.

## Feature design

**Data model**: none (tests only).

**Test layout**:
- `backend/tests/db/conftest.py`: shared fixtures from child 0001; adds `committed_db` (no outer transaction; `TRUNCATE ... RESTART IDENTITY CASCADE` as migrator after each test) and `two_users` (sessions and cookies for A and B, CSRF header preset on their clients).
- `backend/tests/db/test_cross_user.py`: AC-1, AC-2; the matrix maps `(method, path template)` to a builder of path params and a body.
- `backend/tests/db/test_auth_matrix.py`: AC-3, AC-4.
- `backend/tests/db/test_concurrency.py`: AC-5, using `threading.Barrier` with two `TestClient`s over the same app so both requests reach the database together.
- `backend/tests/db/test_migrations.py`, `test_privileges.py`: AC-6, AC-7.
- Marker `db_commit` for tests that commit; they run serially (no xdist).

**Value sourcing**:
| Check | Value | Source |
|---|---|---|
| matrices | route list | `app.routes` filtered to `APIRoute` under `/api/v1` |
| unchanged DB | row counts, last audit id | `SELECT count(*)` per app table, `max(audit_events.id)` |
| migration steps | revision list | `ScriptDirectory.walk_revisions()` |
| scratch DB name | unique name | `energyiq_migr_` plus 8 random hex characters |

**Key invariants**: matrices never hardcode the route list without checking it against the app; no test depends on another test's rows; scratch databases are dropped even on failure.

**Security model**: tests use synthetic emails under `example.test` and generated passwords only.

**Critical test scenarios**: each AC above is its own scenario; the most important failure case is AC-5 (b), concurrent same key requests, verifies **AC-5**; the most important permission case is AC-1, verifies **AC-1**.

## Build plan

1. `two_users` and `committed_db` fixtures, satisfies **AC-1**, **AC-5**
2. Cross user and list isolation matrices with the route coverage check, satisfies **AC-1**, **AC-2**
3. Unauthenticated and CSRF matrices, satisfies **AC-3**, **AC-4**
4. Concurrency tests (a) to (e), satisfies **AC-5**
5. Migration round trip and privilege tests, satisfies **AC-6**, **AC-7**
6. Gate run with and without a database; record evidence in PROGRESS and the roadmap, satisfies **AC-8**
