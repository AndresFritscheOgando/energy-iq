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

## Child 0002: Identity, properties, meters (P2-03)
_Added 2026-11-04 by `/develop`. Start the database and the server first (`docker compose -f infra/compose.yaml up -d db`, `uv run alembic upgrade head`, then the uvicorn command in README). Send `X-EnergyIQ-CSRF: 1` on every POST, PATCH, and DELETE unless a step says otherwise._

### UI / manual (live server, synthetic accounts)
- [x] Register `{email: " Owner@Example.TEST ", password: <12+ chars>}` → 201 `UserOut` with `email` `owner@example.test`, no hash field; `Set-Cookie: energyiq_session=...; HttpOnly; Max-Age=1209600; Path=/; SameSite=lax`, no `Domain`, no `Secure` → AC-1, AC-3
- [x] Register the same email again from a fresh session → 409 `email_taken`, no cookie → AC-1
- [x] Register with an 11 character password, and with `no-at-sign` → 422 `password_length`, 422 `invalid_email` → AC-1
- [x] `GET /api/v1/auth/me` with the cookie → 200 the same user; without it → 401 `not_authenticated`, no `WWW-Authenticate` header → AC-3, AC-4
- [x] Log in with an unknown email, a wrong password, and a disabled user (set `disabled_at` as the migrator) → three 401 `invalid_credentials` bodies identical apart from `request_id` → AC-2
- [x] Log in while sending the register cookie → 200 and a new cookie; the old cookie now gets 401 on `/auth/me` → AC-2
- [x] Logout → 204 with `Max-Age=0`; `/auth/me` with that cookie → 401; logout with no cookie → 204 too → AC-4
- [x] POST the summary without `X-EnergyIQ-CSRF`, with `Origin: http://evil.test`, and with `Origin: null` → 403 `csrf_rejected` each; with the header and `Origin: http://127.0.0.1:8000` → passes → AC-5
- [x] POST the summary with the header but no session → 401; with a session → 200 and the same body as before P2-03 → AC-10
- [x] Five wrong passwords for one email, then the right one → 429 `too_many_attempts` with `Retry-After` near 900 minus the seconds since the first failure → AC-6
- [x] Create property `{nickname: "  Casa  ", region: ""}` → 201, nickname `Casa`, region null, timezone `America/Santo_Domingo` → AC-7
- [x] Create ` casa ` again → 409 `property_name_taken`; archive the first (DELETE → 204), create `CASA` → 201 → AC-7
- [x] PATCH `{}` → 422 `empty_patch`; PATCH `{"timezone": "Mars/Olympus"}` → 422 `invalid_timezone`; PATCH `{"region": null}` → 200 region null → AC-7
- [x] Create meter `{distributor: "EDESUR", label: "Main"}` → 201 active; `MAIN` again → 409 `meter_label_taken`; deactivate → 200 `active: false`; create `main` → 201; PATCH the old meter → 409 `meter_inactive` → AC-8
- [x] `register_digits` `3`, `"6"`, and `true` → 422 `invalid_register_digits`; `4`, `9`, null → 201 → AC-8
- [x] As a second user, GET, PATCH, and DELETE the first user's property, and GET, PATCH, deactivate its meter → 404 bodies identical to a random UUID's apart from `request_id`; the second user's lists are empty → AC-9
- [x] Archived property: GET it, list its meters, GET its meter → 404 everywhere → AC-7, AC-9
- [x] `GET /api/v1/properties?limit=1` with two properties → one item and a `next_cursor`; the next page with that cursor → the other, `next_cursor: null`; `cursor=garbage` → 422 `invalid_cursor` at `["query", "cursor"]` → AC-7

### Value sourcing (vary the source, check the output)
- [x] Current user comes from `sha256(cookie)`: edit one character of the cookie → 401; the stored `sessions.token_hash` equals `sha256` of the cookie and the raw token appears in no table → AC-3
- [x] `email_key` and `client_key` are HMACs with `ENERGYIQ_SECRET_KEY`: restart with a different secret key, then the old failure count no longer applies (a fresh 5 failures are needed for 429); no `auth_attempts` row contains the raw email or `127.0.0.1` → AC-6
- [x] Dummy hash: an unknown email login takes about as long as a wrong password login (one Argon2 verification each) → AC-2
- [x] `expires_at` is login plus 14 days and `last_seen_at` moves only after 5 minutes: read both columns right after login and after two `/auth/me` calls a minute apart → AC-3
- [x] CSRF own origin is scheme plus `Host`: send `Origin: http://localhost:8000` with `Host: localhost:8000` → passes; same `Origin` with `X-Forwarded-Host: localhost:8000` but `Host: 127.0.0.1:8000` → 403 → AC-5
- [x] `Retry-After` comes from the `(n − L + 1)`th oldest counted attempt: with six failures spread over six minutes, the value equals 900 minus the age of the second oldest failure → AC-6
- [x] Maintenance cutoffs: seed attempts 23 h and 25 h old and sessions expired 29 and 31 days ago, run the purge → only the 25 h attempt and the 31 day session go → AC-11
- [x] `owner_user_id` comes from the session, never the body: POST a property with `owner_user_id` → 422 `unknown_field` → AC-7
- [x] Default timezone: create without `timezone` → `America/Santo_Domingo` in the response and the row → AC-7
- [x] Meter `property_id` comes from the path through the owner lookup: create a meter under another user's property id → 404 → AC-8, AC-9
- [x] `id`, `created_at`, `updated_at` come from the server clock: two creates a second apart have increasing `created_at`, and a PATCH moves only `updated_at` → AC-7, AC-8
- [x] Audit `request_id` is the response's `X-Request-ID`: send `X-Request-ID: verify-p2-03` on a property create → the `audit_events` row has that `request_id`, metadata `{"fields": [...]}` with no nickname → AC-10
- [x] Argon2 profile: the stored hash in dev starts with `$argon2id$v=19$m=65536,t=3,p=4`; in tests it uses the cheapest profile → AC-1

### Commands
- [x] `uv run alembic upgrade head`, then `uv run alembic check` → "No new upgrade operations detected" → AC-12
- [x] `uv run alembic downgrade 0001` → `sessions` and `auth_attempts` gone, no `energyiq_app` grants on them; `uv run alembic upgrade head` → grants `SELECT, INSERT` on both and `UPDATE (last_seen_at, revoked_at)` on sessions → AC-12
- [x] `uv run python -m energyiq.platform.maintenance` → exit 0, lines `auth_attempts: N` and `sessions: N` only → AC-11
- [x] `$env:ENERGYIQ_ENV="prod"` with no DSNs set, run the maintenance command → exit 2, stderr names `migration_database_url` → AC-11
- [x] `$env:ENERGYIQ_REQUIRE_DB = "1"; uv run python -m pytest -q -p no:cacheprovider` → all pass; with the database stopped and the variable unset → passes with `db` and `db_commit` tests skipped and the reason printed → umbrella AC-3
- [x] `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` → clean → umbrella AC-3
- [x] `ENERGYIQ_UPDATE_SNAPSHOTS` unset, `uv run pytest backend/tests/api/test_openapi.py` → the snapshot matches and lists 401, 403, 409, 429, 503 where they apply → AC-10

### Acceptance criteria coverage (child 0002)
- AC-1: register, normalization, validation, Argon2 profile steps
- AC-2: identical failures, dummy hash, fixation steps
- AC-3: cookie attributes, token hash, expiry and touch steps
- AC-4: me and logout steps
- AC-5: CSRF header and origin steps
- AC-6: email and client limits, `Retry-After`, HMAC key steps
- AC-7: property create, uniqueness, patch, archive, pagination, defaults steps
- AC-8: meter create, label reuse, deactivate, digits steps
- AC-9: cross user and archived 404 steps
- AC-10: summary behind session, audit, OpenAPI steps
- AC-11: purge cutoffs and maintenance command steps
- AC-12: migration and grant steps
