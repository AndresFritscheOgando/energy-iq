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
| Domain and backend | Python 3.13, FastAPI (planned), modular monolith |
| Data | PostgreSQL (planned) |
| Frontend | Next.js (planned) |
| AI | Local Ollama behind a provider abstraction (planned) |
| Tooling | `uv`, pytest, Ruff, Pyright (strict) |

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

**Next up:** time normalization and coverage (P1-04).

## Documentation

| Topic | Document |
|---|---|
| Product requirements | [01-PRD](docs/01-PRD.md) |
| Architecture | [02-ARCHITECTURE](docs/02-ARCHITECTURE.md) |
| Tech stack decisions | [03-TECH-STACK](docs/03-TECH-STACK.md) |
| Data model and API | [04-DATA-MODEL-API](docs/04-DATA-MODEL-API.md) |
| Roadmap and phase gates | [05-IMPLEMENTATION-ROADMAP](docs/05-IMPLEMENTATION-ROADMAP.md) |
| User stories | [06-USER-STORIES](docs/06-USER-STORIES.md) |
| Testing and AI evaluations | [07-TESTING-EVALUATIONS](docs/07-TESTING-EVALUATIONS.md) |
| Security and operations | [08-SECURITY-OPERATIONS](docs/08-SECURITY-OPERATIONS.md) |
| AI design (Ollama, RAG, MCP) | [10-AI-DESIGN](docs/10-AI-DESIGN.md) |
| Decisions and open questions | [11-DECISIONS-OPEN-QUESTIONS](docs/11-DECISIONS-OPEN-QUESTIONS.md), [ADRs](docs/adr/) |
| Progress log | [PROGRESS](docs/PROGRESS.md) |

## How this project is built

This is a portfolio project, not a commercial product. It is built with an AI coding agent acting as architect and implementation engineer under a written contract: [`AGENTS.md`](AGENTS.md) and the [engineering contract](docs/09-ENGINEERING-CONTRACT.md). Each roadmap ticket gets a spec, tests, review, and a [progress](docs/PROGRESS.md) entry that records only the checks that were actually run. The project does not claim tests pass unless they were run.
