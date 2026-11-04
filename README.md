# EnergyIQ RD

**Electricity intelligence for households in the Dominican Republic.** Track your meters, understand your consumption, check your bills, and eventually ask an AI assistant questions grounded in your own data.

---

## What it will do

- **Multiple properties and meters per user.** Record cumulative kWh readings over time.
- **Consumption analysis.** Turn raw meter readings into trustworthy usage intervals, and catch resets, meter replacements, and suspicious decreases.
- **Bill intelligence.** Upload an electric bill, get proposed fields extracted by AI, and confirm them yourself before anything is saved.
- **Tariff-aware cost estimates** from effective-dated, cited tariff rules, never from a hardcoded "current rate".
- **Forecasting and anomaly detection**, evaluated against simple baselines.
- **An energy assistant** that answers questions from your data and documents, with citations (RAG over a local LLM).
- **Agent actions over MCP** that always need your explicit approval and are audited.

## Design principles

1. **The numbers are computed, not generated.** kWh differences, money totals, and tariffs come from tested, deterministic code. The LLM never invents an authoritative number.
2. **Bills are untrusted input.** AI extraction only proposes values. A human confirms them.
3. **Money is exact.** Amounts use `Decimal` or integer centavos, never floating point.
4. **Privacy first.** Inference runs on a local LLM by default (Ollama). The repository, screenshots, and evaluation data never contain real bills or account details.
5. **No silent actions.** Every consequential write by an agent needs explicit approval and is logged.

## Tech stack

| Layer | Choice |
|---|---|
| Domain and backend | Python 3.13, FastAPI, modular monolith |
| Data | PostgreSQL 18 (Docker Compose), SQLAlchemy 2 (sync) over psycopg 3, Alembic |
| Frontend | Next.js (planned) |
| AI | Local Ollama behind a provider abstraction (planned) |
| Tooling | `uv`, pytest, Hypothesis (property tests), httpx2 (API tests), Ruff, Pyright (strict) |

## Quickstart

You need [uv](https://docs.astral.sh/uv/). Run these commands in PowerShell from the repository root.

```powershell
uv python install 3.13   # install the project's Python version
uv sync                  # create .venv and install dependencies
uv run python -m pytest  # run the test suite
```

### Try the consumption calculator

```powershell
$env:PYTHONPATH = Join-Path $PWD 'backend/src'
uv run python -m energyiq
```

```text
Previous cumulative reading (kWh): 13007.10
Current cumulative reading (kWh): 13007.30
Consumption: 0.20 kWh
```

Type decimal numbers without thousands separators. Negative, decreasing, or invalid input prints a clear error and exits with status 2. The calculator does not store any data.

<details>
<summary>Optional: keep Python and the uv cache inside the repo</summary>

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.cache/uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PWD '.local-python'
uv python install 3.13 --no-bin
uv sync
```

These variables last only for the current terminal session. `.venv`, `.cache`, and `.local-python` are git-ignored.
</details>

### Run the API server

`ENERGYIQ_ENV` has no default: the server, `alembic`, and the maintenance command refuse to start without it (a `missing` error naming `env`), so a deploy can never fall back to dev settings by accident. Set it once per terminal for local work:

```powershell
$env:ENERGYIQ_ENV = "dev"
uv run uvicorn energyiq.main:create_app --factory --app-dir backend/src --no-access-log
```

The server listens on `http://127.0.0.1:8000`. Interactive docs are at `/docs` (hidden when `ENERGYIQ_ENV=prod`). It needs the database below for anything but `/health`. Keep it on localhost and use synthetic data only.

Every `/api/v1` route except register, login, and logout needs a session cookie, and every `POST`, `PATCH`, and `DELETE` needs the header `X-EnergyIQ-CSRF: 1`. Register once, keep the cookie in a web session, then try a summary:

```powershell
$csrf = @{ "X-EnergyIQ-CSRF" = "1" }
$account = @{ email = "you@example.test"; password = "a long synthetic passphrase" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/register -ContentType application/json -Headers $csrf -Body $account -SessionVariable web
# Already registered? Use /api/v1/auth/login with the same body instead.

$body = @{
  meter_id = "00000000-0000-4000-8000-000000000001"
  window   = @{ start = "2026-10-01T00:00:00-04:00"; end = "2026-10-04T00:00:00Z" }
  readings = @(
    @{ id = "00000000-0000-4000-8000-0000000000a1"; recorded_at = "2026-10-01T16:00:00Z"; cumulative_kwh = "13007.10" }
    @{ id = "00000000-0000-4000-8000-0000000000a2"; recorded_at = "2026-10-02T16:00:00Z"; cumulative_kwh = "13019.35" }
  )
} | ConvertTo-Json -Depth 4
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/consumption/summary -ContentType application/json -Headers $csrf -Body $body -WebSession $web
```

The same session reaches the owner scoped routes: `POST /api/v1/properties` with `{"nickname": "Casa"}`, then `POST /api/v1/properties/{id}/meters` with `{"distributor": "EDESUR", "label": "Main"}`. Another user's property or meter always answers 404. Lists take `limit` (1 to 500) and the `next_cursor` of the previous page as `cursor`. See [spec 0009/0002](docs/specs/0009-phase-two-persistence-auth/0002-identity-properties-meters.md).

For that meter, `POST /api/v1/meters/{id}/readings` accepts a decimal string such as `{"local_date":"2026-11-03","cumulative_kwh":"13049"}` or an offset `recorded_at`. `GET` at the same path lists readings. `PATCH /api/v1/meters/{id}/readings/{reading_id}` changes only `status` (`valid`, `flagged`, `voided`). Use `/api/v1/meters/{id}/events` to record a reset or replacement, then `POST` to `/events/{event_id}/approve` or `/reject`. `GET /api/v1/meters/{id}/consumption?from=...&to=...` computes measured kWh and coverage from stored history. Authenticated create and decide POSTs accept an optional `Idempotency-Key` for safe retries; a replay returns the original response with `Idempotent-Replayed: true`. See [spec 0009/0003](docs/specs/0009-phase-two-persistence-auth/0003-readings-events-api.md).

kWh values travel as decimal strings in both directions, timestamps need an explicit offset and come back as UTC `Z` text, and every error is `application/problem+json` with a stable `code`. Settings: `ENERGYIQ_ENV` (`dev`, `test`, `prod`; required), `ENERGYIQ_MAX_BODY_BYTES`, `ENERGYIQ_CORS_ORIGINS` (JSON list), `ENERGYIQ_LOG_LEVEL`, `ENERGYIQ_SESSION_COOKIE_SECURE` (default `true` in `prod`, which also renames the cookie to `__Host-energyiq_session`), and `ENERGYIQ_TRUSTED_ORIGINS` (JSON list of browser origins the CSRF check accepts besides the server's own; default `["http://localhost:3000"]`, required in `prod`). See [spec 0008](docs/specs/0008-minimal-fastapi-application/index.md).

### Run the database

You need Docker with Compose. The database listens on `127.0.0.1:5432` only. The first start creates two roles (`energyiq_migrator` owns the schema, `energyiq_app` is what the API uses) and two databases (`energyiq_dev`, `energyiq_test`).

```powershell
Copy-Item infra/.env.example infra/.env        # synthetic local passwords; infra/.env is git-ignored
docker compose -f infra/compose.yaml up -d db   # start PostgreSQL 18 and wait for "healthy"
uv run alembic upgrade head                      # migrate energyiq_dev as the migrator role
uv run alembic check                             # confirm the ORM and the schema agree
```

These commands also need `$env:ENERGYIQ_ENV = "dev"` (see above). `alembic downgrade base` removes every table. To migrate the test database by hand, set `$env:ENERGYIQ_ENV = "test"` instead. The `dev` and `test` settings default to the values in `infra/.env.example`, so a local run needs no other variables. With `ENERGYIQ_ENV=prod`, `ENERGYIQ_DATABASE_URL`, `ENERGYIQ_MIGRATION_DATABASE_URL`, `ENERGYIQ_SECRET_KEY` (at least 32 characters; it keys the rate limit HMACs), and `ENERGYIQ_TRUSTED_ORIGINS` are required. Optional: `ENERGYIQ_DB_POOL_SIZE` (1 to 50, default 5) and `ENERGYIQ_DB_STATEMENT_TIMEOUT_MS` (100 to 60000, default 5000).

The API still starts without a database. `GET /health` never touches it. `GET /health/ready` answers 200 with the schema revision when the database is reachable and migrated, or a 503 problem with code `database_unavailable` or `schema_out_of_date`. To start over with a fresh volume, run `docker compose -f infra/compose.yaml down -v`.

Expired sessions and old login attempts pile up until you purge them. Nothing schedules this yet, so run it now and then (it connects as the migrator role and prints one count per table):

```powershell
uv run python -m energyiq.platform.maintenance
```

### Quality checks

```powershell
uv run python -m pytest -q    # tests (add -p no:cacheprovider if Windows blocks .pytest_cache)
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
uv run pyright                # strict type checking
```

Tests marked `db` run against `energyiq_test`. The session migrates it to head once, and every test runs in a transaction that is rolled back. The few tests marked `db_commit` (the purge, a live server sign in) commit for real and delete what they wrote. Without a reachable database those tests are skipped and the reason is printed (`PostgreSQL not reachable at 127.0.0.1:5432/energyiq_test`), so the default run still passes. To make a missing database fail the run instead (for CI or before you merge), set the variable first:

```powershell
$env:ENERGYIQ_REQUIRE_DB = "1"; uv run python -m pytest -q; Remove-Item Env:ENERGYIQ_REQUIRE_DB
```

## What's implemented so far

All code lives in [`backend/src/energyiq`](backend/src/energyiq). Tests live in [`backend/tests`](backend/tests).

| Module | What it does | Contract |
|---|---|---|
| `consumption` | Exact kWh difference between two cumulative readings. Rejects negative, decreasing, and non-finite values. | [spec 0001](docs/specs/0001-phase-zero-domain-hardening.md) |
| `observations` | UTC elapsed-time helpers and stable chronological sorting. | [spec 0001](docs/specs/0001-phase-zero-domain-hardening.md) |
| `cli` | The interactive consumption calculator shown above. | [Task 002](docs/tasks/TASK-002-consumption-cli.md) |
| `readings` models | Immutable, validated `Reading` and `MeterEvent` records with UUIDs, UTC instants, and bounded `Decimal` kWh. | [spec 0002](docs/specs/0002-reading-meter-event-models.md) |
| `readings.order_readings` | Sorts one meter's readings and reports any duplicate-timestamp conflicts. | [spec 0003](docs/specs/0003-reading-order-conflicts.md) |
| `readings.compute_intervals` | Builds consumption intervals and marks an interval invalid, with a reason, when it crosses a meter event, a flagged reading, or a decrease. | [spec 0004](docs/specs/0004-reading-interval-boundaries/index.md) |
| `readings.normalize_intervals`, `readings.summarize_consumption` | Turns intervals into kWh per day using real elapsed time, and summarizes a time window: measured kWh, how much of the window is covered, and a typed gap for every span with missing data. Nothing is estimated. | [spec 0005](docs/specs/0005-time-normalized-consumption-coverage/index.md) |

| `platform.db`, `platform.http.ready`, ORM rows, `backend/alembic` | PostgreSQL foundation: a lazy engine (UTC, statement timeout), per request sessions, revision `0001` with the core tables and named constraints, column level grants for the app role, `GET /health/ready`, and 503 `database_unavailable` for connection, pool, and statement timeouts. No user data routes yet. | [spec 0009/0001](docs/specs/0009-phase-two-persistence-auth/0001-database-foundation.md) |
| `identity`, `properties`, `platform.http.csrf`, `platform.pagination`, `platform.audit`, `platform.maintenance` | Accounts with Argon2id passwords and server sessions in an HttpOnly cookie (14 day absolute, 24 hour idle), a header plus `Origin` CSRF check on every unsafe route, database backed login and register rate limits with `Retry-After`, owner scoped property and meter CRUD with archive and deactivation, keyset pagination, an audit row for every write, and the purge command. Revision `0002`. The summary route now needs a session. | [spec 0009/0002](docs/specs/0009-phase-two-persistence-auth/0002-identity-properties-meters.md) |
| `readings.persistence`, `readings.api.stored_router`, `platform.idempotency` | Owner scoped stored reading and event routes, status and decision transitions, date only noon conversion, paginated lists, safe POST replay, and consumption from stored history. Revision `0003`. | [spec 0009/0003](docs/specs/0009-phase-two-persistence-auth/0003-readings-events-api.md) |
| `main`, `platform`, `readings.api` | FastAPI app: `GET /health` and the stateless `POST /api/v1/consumption/summary`, with problem details errors, request ids, a JSON access log, body caps, settings, and CORS. | [spec 0008](docs/specs/0008-minimal-fastapi-application/index.md) |

Property based tests (P1-05, [spec 0006](docs/specs/0006-reading-chain-property-tests/index.md)) check ordering, interval rules, window tiling, and additivity across generated reading chains. Set `ENERGYIQ_HYPOTHESIS_PROFILE=deep` for a wider random search.

**Next up:** P2-05, the Phase 2 security, concurrency, and migration gate tests ([spec 0009/0004](docs/specs/0009-phase-two-persistence-auth/0004-phase-two-gate-tests.md)). Reading semantics and discontinuity rules are documented in [12-METER-SEMANTICS](docs/12-METER-SEMANTICS.md) (P1-06).

## Documentation

| Topic | Document |
|---|---|
| Product requirements | [01-PRD](docs/01-PRD.md) |
| Architecture | [02-ARCHITECTURE](docs/02-ARCHITECTURE.md) |
| Tech stack decisions | [03-TECH-STACK](docs/03-TECH-STACK.md) |
| Data model and API | [04-DATA-MODEL-API](docs/04-DATA-MODEL-API.md) |
| Meter semantics and discontinuity rules | [12-METER-SEMANTICS](docs/12-METER-SEMANTICS.md) |
| Roadmap and phase gates | [05-IMPLEMENTATION-ROADMAP](docs/05-IMPLEMENTATION-ROADMAP.md) |
| User stories | [06-USER-STORIES](docs/06-USER-STORIES.md) |
| Testing and AI evaluations | [07-TESTING-EVALUATIONS](docs/07-TESTING-EVALUATIONS.md) |
| Security and operations | [08-SECURITY-OPERATIONS](docs/08-SECURITY-OPERATIONS.md) |
| AI design (Ollama, RAG, MCP) | [10-AI-DESIGN](docs/10-AI-DESIGN.md) |
| Decisions and open questions | [11-DECISIONS-OPEN-QUESTIONS](docs/11-DECISIONS-OPEN-QUESTIONS.md), [ADRs](docs/adr/) |
| Progress log | [PROGRESS](docs/PROGRESS.md) |
