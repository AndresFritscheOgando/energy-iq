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
| Data | PostgreSQL (planned) |
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

```powershell
uv run uvicorn energyiq.main:create_app --factory --app-dir backend/src --no-access-log
```

The server listens on `http://127.0.0.1:8000`. Interactive docs are at `/docs` (hidden when `ENERGYIQ_ENV=prod`). It stores nothing and has no login yet, so keep it on localhost and use synthetic data only. Try a summary:

```powershell
$body = @{
  meter_id = "00000000-0000-4000-8000-000000000001"
  window   = @{ start = "2026-10-01T00:00:00-04:00"; end = "2026-10-04T00:00:00Z" }
  readings = @(
    @{ id = "00000000-0000-4000-8000-0000000000a1"; recorded_at = "2026-10-01T16:00:00Z"; cumulative_kwh = "13007.10" }
    @{ id = "00000000-0000-4000-8000-0000000000a2"; recorded_at = "2026-10-02T16:00:00Z"; cumulative_kwh = "13019.35" }
  )
} | ConvertTo-Json -Depth 4
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/consumption/summary -ContentType application/json -Body $body
```

kWh values travel as decimal strings in both directions, timestamps need an explicit offset and come back as UTC `Z` text, and every error is `application/problem+json` with a stable `code`. Settings: `ENERGYIQ_ENV` (`dev`, `test`, `prod`), `ENERGYIQ_MAX_BODY_BYTES`, `ENERGYIQ_CORS_ORIGINS` (JSON list), `ENERGYIQ_LOG_LEVEL`. See [spec 0008](docs/specs/0008-minimal-fastapi-application/index.md).

### Quality checks

```powershell
uv run python -m pytest -q    # tests (add -p no:cacheprovider if Windows blocks .pytest_cache)
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
uv run pyright                # strict type checking
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

| `main`, `platform`, `readings.api` | FastAPI app: `GET /health` and the stateless `POST /api/v1/consumption/summary`, with problem details errors, request ids, a JSON access log, body caps, settings, and CORS. | [spec 0008](docs/specs/0008-minimal-fastapi-application/index.md) |

Property based tests (P1-05, [spec 0006](docs/specs/0006-reading-chain-property-tests/index.md)) check ordering, interval rules, window tiling, and additivity across generated reading chains. Set `ENERGYIQ_HYPOTHESIS_PROFILE=deep` for a wider random search.

**Next up:** P2-02, PostgreSQL with SQLAlchemy mappings and an Alembic migration. Reading semantics and discontinuity rules are documented in [12-METER-SEMANTICS](docs/12-METER-SEMANTICS.md) (P1-06).

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