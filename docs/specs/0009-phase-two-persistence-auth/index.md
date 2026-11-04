# 0009. Phase 2 persistence, identity, and stored readings

**Date**: 2026-11-04
**Status**: In Progress

## Summary

This umbrella spec covers the rest of Phase 2 (P2-02 to P2-05). It adds a local PostgreSQL database with migrations, user accounts with cookie sessions, owner scoped properties and meters, and an API that stores readings and meter events and computes consumption from them. Every query is scoped to the signed in owner, every write is audited, and a repeated POST with the same `Idempotency-Key` header (a client chosen retry token) is answered once. The work is split into four child specs, one per ticket, built in roadmap order.

## Structure

| Child | Ticket | What it decides |
|---|---|---|
| [0001 Database foundation](0001-database-foundation.md) | P2-02 | Compose PostgreSQL 18, two database roles, SQLAlchemy 2 sync engine with psycopg 3, Alembic, the core schema and its constraints, readiness check, test database fixtures |
| [0002 Identity, properties, meters](0002-identity-properties-meters.md) | P2-03 | Registration, login, server sessions in an HttpOnly cookie, Argon2id, CSRF defense, database backed rate limits, owner scoped property and meter CRUD, soft delete, meter deactivation |
| [0003 Readings and events API](0003-readings-events-api.md) | P2-04 | Stored readings (single POST, status changes only), meter events with pending, approved, rejected states, idempotency keys, date only conversion, keyset pagination, stored consumption endpoint |
| [0004 Phase 2 gate tests](0004-phase-two-gate-tests.md) | P2-05 | Cross user access matrix, unauthenticated and CSRF matrices, duplicate and concurrent request tests, migration upgrade and downgrade round trips, database privilege tests |

Child files are numbered inside this directory only. The next top level spec number is 0010.

## Requirements

**User stories**:
- As a household owner, I want an account and my own properties, meters, and readings, so my energy history is private to me.
- As the P3 Next.js client, I want one stable, authenticated, paginated JSON API with the 0008 error shape, so screens never special case errors.
- As an operator, I want reversible migrations, audited writes, and safe retries, so data stays correct under failure and duplicates.

**Acceptance criteria** (umbrella level; each child holds its own detailed ACs):
- **AC-1**: Every child's acceptance criteria pass, built in order 0001 → 0002 → 0003 → 0004.
- **AC-2**: The Phase 2 exit gate holds: isolated REST CRUD (child 0004 cross user matrix), migrations upgrade and downgrade cleanly (child 0004), and integration tests run against real PostgreSQL with `ENERGYIQ_REQUIRE_DB=1`.
- **AC-3**: The full suite (existing 516 tests plus new ones), Ruff lint and format, and strict Pyright pass. Without a reachable database, the default run still passes, with every `db` marked test skipped and the reason printed.
- **AC-4**: The 0008 conventions hold on every new route: problem details errors, `X-Request-ID`, decimal strings, UTC `Z` timestamps, body caps, unknown fields rejected, and no body, query, header value, or client address in logs.
- **AC-5**: Importing `energyiq.readings` in a fresh interpreter loads none of `fastapi`, `starlette`, `pydantic`, `sqlalchemy`, `psycopg` (the 0008 boundary test, extended).
- **AC-6**: README, `docs/03-TECH-STACK.md` (pinned versions), `docs/04-DATA-MODEL-API.md` (endpoints, error catalog), `docs/11-DECISIONS-OPEN-QUESTIONS.md` (open decision 1 closed), `docs/12-METER-SEMANTICS.md` (stored date only collisions), the roadmap, and `docs/PROGRESS.md` are updated, and ADR-007 (session auth) is recorded.

## Decision

**Chosen option**: Option 2: a sync SQLAlchemy modular monolith with server sessions, owner scoped repositories, and stored idempotency keys.

Use PostgreSQL 18 in Compose, SQLAlchemy 2 (sync) over psycopg 3, Alembic with hand reviewed migrations, opaque server sessions in an HttpOnly cookie with Argon2id passwords, ownership enforced inside every repository query, and a per request explicit transaction that holds the write, its audit row, and its idempotency record together.

**Implementation skills**: `fastapi` (`fastapi/fastapi`, `.agents/skills/fastapi/`): `Annotated` dependencies, router level dependencies, `yield` dependency scopes · `sqlalchemy-alembic-expert-best-practices-code-review` (`wispbit-ai/skills`, `.agents/skills/sqlalchemy-alembic-expert-best-practices-code-review/`): typed models, migration safety · `supabase-postgres-best-practices` (Supabase plugin, installed at user level, not in the project skills dir): foreign key indexes, `timestamptz`, lowercase identifiers, short transactions, one lock order, least privilege roles, keyset pagination.

## Rationale

Reasoning, options, and every sub decision with its runner up: see [rationale.md](rationale.md).

## Cross child contract

These rules bind all four children. A child may add detail, never contradict them.

**Module layout** (from `docs/02-ARCHITECTURE.md`):
- `platform/db.py`: `Base` (declarative, constraint naming convention), `build_engine(settings)`, `get_db_session` dependency, `constraint_name(exc)` helper for `IntegrityError`.
- `platform/audit.py`, `platform/idempotency.py`, `platform/pagination.py`, `platform/maintenance.py`, `platform/http/csrf.py`, `platform/http/ready.py`.
- `identity/` (users, sessions, passwords, rate limits, auth routes), `properties/` (properties, meters), `readings/persistence/` (ORM rows, repositories, row to domain mapping), `readings/api/` (existing summary router plus the stored routers).
- `backend/alembic/` (env, versions), `alembic.ini` at the repo root, `infra/compose.yaml`, `infra/.env.example`, `infra/db/init/`.
- `energyiq/readings/__init__.py` stays unchanged and imports no persistence code (AC-5).

**Constraint naming convention** (set on `Base.metadata`, so migrations and error mapping agree): `pk_%(table_name)s`, `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`, `uq_%(table_name)s_%(column_0_name)s`, `ck_%(table_name)s_%(constraint_name)s`, `ix_%(table_name)s_%(column_0_name)s`. Partial unique indexes get explicit names, listed in child 0001.

**Transactions**:
- `get_db_session` yields one `Session` (`expire_on_commit=False`) per request and closes it; it never commits. FastAPI's default `yield` exit runs after the response is sent, so no commit may live there.
- Each write use case opens exactly one `with session.begin():` inside the handler call path, so a commit failure surfaces before the response. The write, its `audit_events` row, and its `idempotency_keys` row commit or roll back together. Every read the route does happens inside that block (or inside its own `begin()` for read only routes); nothing touches the session between the auth dependency and the route's `begin()`, which would autobegin a transaction and make `begin()` raise.
- The auth dependency runs its own short transaction (session lookup and idle touch), commits, and returns a frozen `CurrentUser(id, email)` value, never an ORM object.
- **Security records that must survive a failed request** (`auth_attempts` rows and `auth.login_failed` or failed `auth.register` audit rows) are committed in their own short transaction before the 401, 409, or 429 is raised.
- **Lock order** inside a write transaction, always the same: (1) the `idempotency_keys` row when a key is sent, (2) the meter row (`SELECT ... FOR UPDATE OF meters`, filtered only by id and ownership, never by `active`; `active` is checked after the lock so a racing deactivate yields 409, not 404). The `sessions.last_seen_at` touch happens in the auth transaction, before either. Auth attempt checks take `pg_advisory_xact_lock` on the first 8 bytes of the email key (login) or client key (register). Each transaction takes these in this order and no other row locks, so deadlocks cannot form.
- Isolation level is the PostgreSQL default, READ COMMITTED. Unique indexes are the final arbiter of duplicates. A unique violation aborts the PostgreSQL transaction, so no statement may run after an `IntegrityError` in the same transaction: the handler rolls back, maps the constraint name to its problem code, and if the problem needs a looked up value (for example `existing_reading_id`) it reads it in a new short transaction. Where a lock already serializes the writers (readings under the meter lock), the use case looks the conflict up first under the lock and keeps the index as the backstop.

**Ownership**: every repository function that reads or writes owned data takes `owner_id: UUID` as a required positional parameter and joins `properties.owner_user_id = owner_id AND properties.archived_at IS NULL` in the same SQL statement. Not owned, archived, and nonexistent are the same result, `None`, which the route turns into 404 `not_found`. No route loads a row first and checks ownership afterwards.

**Error catalog additions** (extend the 0008 table in `docs/04-DATA-MODEL-API.md`; `detail` strings are fixed per code):

| Status | `code` | When | `detail` |
|---|---|---|---|
| 400 | `invalid_idempotency_key` | header present but not 1 to 255 visible ASCII characters | `The Idempotency-Key header is invalid.` |
| 401 | `not_authenticated` | no valid session (missing, unknown, expired, idle, revoked, disabled user) | `Authentication is required.` |
| 401 | `invalid_credentials` | login with an unknown email, wrong password, or disabled user | `The email or password is incorrect.` |
| 403 | `csrf_rejected` | unsafe method without `X-EnergyIQ-CSRF: 1`, or a foreign or `null` `Origin` | `The request failed cross site request checks.` |
| 404 | `not_found` | resource not found or not owned (same body as an unknown path) | `No resource exists at this path.` |
| 409 | `email_taken` | registration email already exists | `An account with this email already exists.` |
| 409 | `property_name_taken` | nickname in use among the owner's non archived properties | `A property with this nickname already exists.` |
| 409 | `meter_label_taken` | label in use among the property's active meters | `An active meter with this label already exists.` |
| 409 | `meter_inactive` | create reading or event, PATCH, or deactivate on an inactive meter | `The meter is inactive.` |
| 409 | `reading_exists_at_instant` | a non voided reading already exists at that UTC instant (member `existing_reading_id`) | `A reading already exists at this instant.` |
| 409 | `reading_voided` | status change on a voided reading | `A voided reading cannot change status.` |
| 409 | `event_not_pending` | approve or reject an event that is not pending | `The event has already been decided.` |
| 409 | `idempotency_key_reused` | same key, different operation or body | `The Idempotency-Key was used for a different request.` |
| 429 | `too_many_attempts` | auth rate limit hit (header `Retry-After` in seconds) | `Too many attempts. Try again later.` |
| 503 | `database_unavailable` | connection failure, pool timeout, or statement timeout | `The service is temporarily unavailable.` |
| 503 | `schema_out_of_date` | readiness only: database revision is not the code's head | `The database schema is not up to date.` |

The 0008 `validation_error` detail changes from `The request body failed validation.` to `The request failed validation.`, because query parameters now validate too (snapshot and 0008 tests updated on purpose).

The stateless summary keeps 422 `reading_timestamp_conflict` for posted data; stored data uses 409 `reading_exists_at_instant`, a different code, because the meaning differs.

**Validation catalog additions** (`errors[].code` → `message`): `invalid_email` → `Value must be an email address.`; `password_length` → `Password must be 12 to 128 characters.`; `invalid_timezone` → `Value must be an IANA time zone name.`; `invalid_text_length` → `Text length is out of range.`; `reading_in_future` → `Value cannot be in the future.`; `exactly_one_of` → `Give exactly one of recorded_at or local_date.`; `range_order` → `to must be after from.` (query ranges, loc `["query", "to"]`); `window_too_long` → `The window cannot exceed 366 days.` (loc `["query", "to"]`); `invalid_cursor` → `Cursor is invalid.`; `empty_patch` → `Give at least one field to change.`; `invalid_register_digits` → `Value must be an integer from 4 to 9.`

**Check order on every route**: 404 or 405 (routing) → 413 (middleware) → 403 `csrf_rejected` → 415 → 400 `invalid_idempotency_key` → 401 → 422 → 429 (login and register only) → idempotent replay (a stored response wins over every later check) → 404 `not_found` (ownership) → 409 → write. FastAPI parses JSON before dependencies run, so a malformed body may answer 400 `malformed_json` ahead of 403 or 401; that is accepted and tested as such. 401 responses carry no `WWW-Authenticate` header: cookie sessions have no registered HTTP auth scheme, and this deviation from RFC 9110 is accepted and documented in `04-DATA-MODEL-API.md`.

**Pagination** (every list): query `limit` (1 to 500, default 100) and `cursor`; response `{"items": [...], "next_cursor": string | null}`. The cursor is unpadded base64url of compact JSON `{"k": [<sort key text>, <id>]}`, where the sort key text is the 0008 `format_utc` of the timestamp (it keeps microseconds, so the key round trips exactly); anything that fails to decode or type check is 422 `invalid_cursor` at `["query", "cursor"]`. A cursor is not bound to the filters it was issued with: it only means "rows after this key", applied with whatever filters the next request sends. Sort keys: properties and meters `(created_at, id)`, readings `(recorded_at, id)`, events `(effective_at, id)`, all ascending.

**Audit**: `record_audit(session, actor_id, action, entity_type, entity_id, request_id, metadata)` in the write's transaction (or in the security record transaction for failed auth). `entity_type` is one of `user`, `property`, `meter`, `reading`, `meter_event`. Metadata holds only field names and state transitions, never email, password, nickname, note text, token, or IP. Idempotent replays and no op status changes write no audit row. Actions: `auth.register`, `auth.login`, `auth.login_failed`, `auth.logout`, `property.create`, `property.update`, `property.archive`, `meter.create`, `meter.update`, `meter.deactivate`, `reading.create`, `reading.status_change`, `event.create`, `event.approve`, `event.reject`.

**Settings additions** (`ENERGYIQ_*`; `prod` requires the URLs and the secret explicitly, `dev` and `test` default to the values in `infra/.env.example`):
- `ENERGYIQ_DATABASE_URL` (`SecretStr`): app role DSN, `postgresql+psycopg://energyiq_app:...@127.0.0.1:5432/energyiq_dev` (test: `energyiq_test`).
- `ENERGYIQ_MIGRATION_DATABASE_URL` (`SecretStr`): migrator role DSN, used by Alembic, the maintenance command, and test setup only.
- `ENERGYIQ_DB_POOL_SIZE` (default 5, 1 to 50) and `ENERGYIQ_DB_STATEMENT_TIMEOUT_MS` (default 5000, 100 to 60000).
- `ENERGYIQ_SECRET_KEY` (`SecretStr`, at least 32 characters): HMAC key for rate limit keys. `dev` and `test` default to the fixed synthetic value in `infra/.env.example`, so counts survive restarts and agree across workers and `--reload` processes.
- `ENERGYIQ_SESSION_COOKIE_SECURE` (bool, default `true` in `prod`, `false` otherwise).
- `ENERGYIQ_TRUSTED_ORIGINS` (JSON list of origins): origins allowed by the CSRF `Origin` check besides the request's own origin, separate from `ENERGYIQ_CORS_ORIGINS`. Default `["http://localhost:3000"]` in `dev` and `test`, required (non empty) in `prod`, where the browser's origin is the Next.js proxy's public origin. uvicorn runs with its default `--proxy-headers` and `--forwarded-allow-ips` loopback only, so `request.client.host` and the scheme reflect `X-Forwarded-*` only from a local proxy; the CSRF check never trusts `X-Forwarded-Host`.
- `ENERGYIQ_REQUIRE_DB` (tests only, read by `conftest.py`, not `Settings`): `1` turns skipped `db` tests into failures.

`create_app` builds the engine lazily (no connection at startup), so `GET /health` and all existing tests still run with no database. The app lifespan disposes the engine at shutdown, so repeated `create_app` calls in tests do not leak pools. Engine options: `pool_pre_ping=True`, `pool_timeout=5`, `connect_args={"connect_timeout": 2, "options": "-c timezone=UTC -c statement_timeout=<ms>"}`.

**CORS**: unchanged credential policy (`allow_credentials=False`). The P3 client will call the API through a Next.js same origin proxy (ADR-007). Allowed methods grow to `GET`, `POST`, `PATCH`, `DELETE`; allowed headers add `X-EnergyIQ-CSRF` and `Idempotency-Key`; exposed headers add `Retry-After` and `Idempotent-Replayed`.

**Dependencies** (verify each against official docs for Python 3.13 and pin the tested versions in `uv.lock` at build time; do not guess versions here): runtime `sqlalchemy` 2.x, `alembic`, `psycopg[binary]` 3.x, `argon2-cffi`, `tzdata`. No new dev dependency.

## Build plan

Tracer Bullet (no approach recorded in the repo; assumed default). The roadmap fixes the child order, and each child starts with a thin end to end thread before it thickens:

1. Build child 0001 (P2-02): Compose up, one migration, readiness check through the real app, then the full schema and fixtures, satisfies **AC-1**, **AC-3**, **AC-5**
2. Build child 0002 (P2-03): register and `GET /auth/me` through a real session first, then login, logout, CSRF, rate limits, properties, meters, satisfies **AC-1**, **AC-4**
3. Build child 0003 (P2-04): create and list one reading first, then events, status changes, idempotency, date only input, stored consumption, satisfies **AC-1**, **AC-4**
4. Build child 0004 (P2-05): the enumerated security matrices, concurrency, and migration round trips, satisfies **AC-1**, **AC-2**
5. Docs, ADR-007, OpenAPI snapshot regeneration, full checks with `ENERGYIQ_REQUIRE_DB=1` and without a database, satisfies **AC-3**, **AC-6**

## Consequences

**Positive**:
- Ownership lives in one query pattern, so the cross user matrix proves it for every route at once.
- Revocable sessions, audited writes, and idempotent POSTs are in place before the UI, agents, and MCP tools (P3, P7) build on them.
- The app role cannot delete rows, change schema, or update any column except the listed status and decision columns, so reading values, times, and audit rows are append only by privilege, not just by convention.

**Negative / tradeoffs**:
- Docker is now required for integration tests and local runs that touch data; domain only work still runs without it.
- Cookie sessions need CSRF handling and a same origin proxy in P3; non browser clients (CLI, MCP) need a cookie jar until a token path is designed.
- Two database roles and two DSNs add setup steps and settings.
- Sync SQLAlchemy ties throughput to the threadpool (40 workers by default); fine for one household, revisit before multi user load.
- No scheduler exists, so expired sessions, attempts, and idempotency keys pile up until someone runs the maintenance command.

**Neutral**:
- Three Alembic revisions (`0001`, `0002`, `0003`), one per ticket.
- The OpenAPI snapshot grows a lot and is regenerated on purpose.
- The stateless summary endpoint now needs a session.

## Follow-up

- [ ] Close the P2-01 review minors and mark spec 0008 Accepted before child 0001 starts (PROGRESS next action).
- [ ] ADR-007: server sessions in an HttpOnly cookie with same origin proxy (written in build step 5).
- [ ] P3-01: build the Next.js `/api` rewrite to FastAPI; the browser sends `X-EnergyIQ-CSRF: 1` on unsafe methods.
- [ ] P7: design a token path (or MCP side session) for non browser clients.
- [ ] P8: schedule `python -m energyiq.platform.maintenance`, add a breached password check, and add rate limits to write endpoints.
- [ ] Meter reactivation and email verification are out of scope; revisit when the UI shows a need.
- [ ] Optional read only PostgreSQL MCP server for the dev database (deferred, "not now"): candidates `milad-codes/pg-readonly-mcp`, `contextflo/postgres-mcp`; maintenance status unverified.
- [ ] `/sync`: add the `fastapi` and `sqlalchemy-alembic-expert-best-practices-code-review` skills to `AGENTS.md` `## Agent skills` (root, project wide). No credible psycopg 3 or argon2 skill exists; use the official docs.
- [ ] `/sync`: record PostgreSQL, SQLAlchemy, Alembic, psycopg, argon2-cffi, tzdata, the Compose commands, and the ownership and transaction rules in `AGENTS.md`.
