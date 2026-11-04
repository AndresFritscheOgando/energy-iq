# 0009 rationale: Phase 2 persistence, identity, and stored readings

## Context

Phase 1 left a correct, framework free reading domain, and P2-01 (spec 0008) put it behind a stateless HTTP endpoint that stores nothing and knows no users. The Phase 2 exit gate needs isolated REST CRUD, migrations, and integration tests. That means choosing how data is stored, how a user is identified, how ownership is enforced, and how writes stay correct when requests repeat or race.

The forces that shaped it:
- **Ownership is load bearing.** Invariant 7 in `04-DATA-MODEL-API.md` requires owner checks on every property, meter, reading, and later bill, document, chunk, and tool. Agents and MCP (P7) will call the same services, so the check must live where it cannot be skipped.
- **History must not be rewritten.** Readings are cumulative observations, and spec 0007 forbids inferring resets or fabricating values. Stored data must stay conflict free for `compute_intervals`, and corrections must not erase what was observed.
- **Retries happen.** Mobile networks and the future UI resend POSTs, so a duplicate POST must never create a second reading.
- **Small team, local first.** One developer, Docker Compose, no queue or cache allowed until a phase needs one (`AGENTS.md`). Routes are already sync `def` in the threadpool.
- **Privacy by default.** Synthetic data only, no PII in logs or audit metadata, and no raw client addresses stored.

Without these decisions, P3 would build against an unstable contract and P2-05 would have nothing concrete to test.

## Options considered

### Option 1: Thin CRUD, ownership checked in routes

Routes load rows by id, then compare `owner_user_id`. Plain bearer JWTs, no idempotency store, no audit table.

**Pros**: least code; quick to show endpoints.
**Cons**: one forgotten check is an IDOR (a user reading another user's data by guessing ids); JWTs cannot be revoked on logout; duplicate POSTs create duplicate readings; no trail for invariant 8.

### Option 2: Sync SQLAlchemy monolith, owner scoped repositories, server sessions, stored idempotency (chosen)

Ownership is part of every repository query. Opaque session tokens live in an HttpOnly cookie and only their hashes are stored. One explicit transaction per write holds the write, its audit row, and its idempotency record.

**Pros**: ownership proven structurally and by an enumerated test matrix; instant session revocation; safe retries; audit from day one; same sync style as P2-01.
**Cons**: more tables and settings; CSRF and a same origin proxy needed for browsers; sync throughput bound by the threadpool.

### Option 3: Async stack with PostgreSQL row level security

Async SQLAlchemy over asyncpg, and RLS (database enforced per row policies) keyed on a `SET app.user_id` per transaction.

**Pros**: the database itself enforces ownership; higher concurrency ceiling.
**Cons**: every route, test, and fixture changes to async; RLS with pooled connections needs careful `SET LOCAL` discipline, and its failures are silent empty results; much harder to debug for one developer at this stage.

## Rationale

Option 2 fits the forces best. Putting `owner_id` into every repository signature and SQL statement makes the IDOR class structurally hard to write, and the P2-05 matrix enumerates `app.routes`, so a new route without coverage fails the build. That gives most of RLS's safety without its pooled connection pitfalls. Option 3 stays possible later as defense in depth. Server sessions were chosen over JWTs because logout and account disable must take effect immediately, and the browser never has to hold a token readable by JavaScript. Stored idempotency keys plus partial unique indexes cover both retries and races. Option 1 fails invariants 7 and 8 outright.

Sub decisions (pick, why, runner up):
- **PostgreSQL 18** in Compose, exact image tag pinned at build; runner up 17 if a later extension (pgvector) lags.
- **psycopg 3 sync driver**, matching the existing sync routes; runner up asyncpg with async SQLAlchemy, deferred until profiling shows a need.
- **Two roles** (`energyiq_migrator` owns the schema, `energyiq_app` has only SELECT, INSERT, UPDATE): append only readings by privilege; runner up a single owner role, simpler but lets an app bug drop or delete data.
- **TEXT plus CHECK for enumerations**: adding a value is a constraint swap; runner up native ENUM, which cannot drop values.
- **UUIDv4 generated in the app**, matching the domain models; runner up `uuidv7()` in PostgreSQL 18, which would split id generation between app and database.
- **Argon2id via argon2-cffi** (RFC 9106 low memory profile; `argon2.profiles.CHEAPEST` in `test`); runner up pwdlib, a wrapper over the same library.
- **CSRF**: `SameSite=Lax`, a required custom header (it forces a CORS preflight, so cross site forms cannot send it), and an `Origin` check; runner up a double submit token.
- **Rate limits in PostgreSQL** (`auth_attempts` with HMAC keys, never raw IPs or emails): survive restarts and multiple workers with no Redis; runner up an in process limiter.
- **Sessions**: 14 days absolute, 24 hours idle, touch at most every 5 minutes; runner up 7 days absolute only.
- **Idempotency**: an `Idempotency-Key` header stored per user for 24 hours, with the response replayed; runner up client supplied ids, which only cover one resource.
- **Same instant reading**: 409 through a partial unique index, so stored chains never conflict; runner up storing both and surfacing the conflict at read time.
- **Status change only corrections**, voided terminal; runner up editable values, which rewrite history.
- **Event lifecycle** pending → approved or rejected; pending events block intervals exactly as P1-03 treats unapproved events; runner up deleting pending events.
- **Soft delete** of properties via `archived_at`; runner up blocking deletion while meters exist.
- **Keyset pagination**; runner up limit and offset.
- **Consumption window** required, at most 366 days; runner up a 30 day default.
- **tzdata** for `ZoneInfo` on Windows; runner up a fixed UTC−4 constant, wrong for any non DR property.
- **Same origin proxy for P3** instead of credentialed CORS, which keeps the 0008 CORS policy credential free.
- **Test database**: Compose PostgreSQL with per test rollback through savepoints; runner up testcontainers (hermetic, but a new dependency and slower startup).
- **Explicit commit in the use case**, not in a yield dependency's exit: with FastAPI's default `"request"` scope that exit runs after the response is sent, so a commit failure would reach no client. Runner up `Depends(..., scope="function")`, which commits before sending but hides the transaction boundary from the use case.
- **Maintenance command run by hand** for purges; a scheduler is a P8 concern.
