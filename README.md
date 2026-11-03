# EnergyIQ RD — Energy Intelligence Platform

**Status:** Phase 0 is complete. Phase 1 P1-01 through P1-03 reading models, ordering, conflicts, and interval boundaries are implemented. The latest suite passed 254 tests. Time normalization and coverage are next.
**Delivery model:** The assistant acts as software architect and implementation engineer, delivering complete features, tests, and documentation.  
**Goal:** Build a production-oriented, portfolio-quality electricity intelligence product for the Dominican Republic, through architect-led implementation following the product specifications and roadmap.

## Product in one paragraph
EnergyIQ RD manages several properties and meters per user; accepts timestamped cumulative meter readings; analyzes consumption and billing; ingests electric bills for verified extraction; supports forecasting, anomaly detection, evidence-based AI explanations, document search via RAG, and eventually authorized agent actions through an MCP interface. Start with deterministic domain logic. AI is introduced only after baseline measurements and evaluation datasets exist.

## Read this documentation in order
1. [`AGENTS.md`](AGENTS.md) and [`CLAUDE.md`](CLAUDE.md) — mandatory architecture and implementation instructions.
2. [`docs/01-PRD.md`](docs/01-PRD.md) — outcomes, users, scope and acceptance criteria.
3. [`docs/02-ARCHITECTURE.md`](docs/02-ARCHITECTURE.md) — modular design, data flows, deployment boundaries.
4. [`docs/03-TECH-STACK.md`](docs/03-TECH-STACK.md) — technology decisions and setup rules.
5. [`docs/04-DATA-MODEL-API.md`](docs/04-DATA-MODEL-API.md) — data contracts, invariants, API outline.
6. [`docs/05-IMPLEMENTATION-ROADMAP.md`](docs/05-IMPLEMENTATION-ROADMAP.md) — incremental phases and gates.
7. [`docs/06-USER-STORIES.md`](docs/06-USER-STORIES.md) — backlog and acceptance cases.
8. [`docs/07-TESTING-EVALUATIONS.md`](docs/07-TESTING-EVALUATIONS.md) — software and AI quality gates.
9. [`docs/08-SECURITY-OPERATIONS.md`](docs/08-SECURITY-OPERATIONS.md) — security, observability and production standards.
10. [`docs/09-ENGINEERING-CONTRACT.md`](docs/09-ENGINEERING-CONTRACT.md) — implementation responsibilities, verification, and delivery workflow.
11. [`docs/10-AI-DESIGN.md`](docs/10-AI-DESIGN.md) — local Ollama, document extraction, RAG, tools, MCP.
12. [`docs/11-DECISIONS-OPEN-QUESTIONS.md`](docs/11-DECISIONS-OPEN-QUESTIONS.md) — ADR index, assumptions and unresolved issues.
13. [`docs/adr/`](docs/adr/) — architectural decision records.
14. [`docs/tasks/TASK-001-consumption-foundations.md`](docs/tasks/TASK-001-consumption-foundations.md) and [`docs/tasks/TASK-002-consumption-cli.md`](docs/tasks/TASK-002-consumption-cli.md) — foundation and CLI contracts.
15. [`docs/PROGRESS.md`](docs/PROGRESS.md) — implemented behavior, actual verification, gaps, and next task.

## Locked user decisions
- Support **personal monitoring, multiple households/properties, bill intelligence and long-term full energy intelligence**.
- Use a **modular monolith**, not microservices.
- Build a **full-stack app**: Next.js, FastAPI, PostgreSQL, tests, Docker.
- The assistant acts as **architect and implementation engineer**: it implements domain logic, APIs, integrations, AI workflows, tests, and documentation directly. Advancement depends on technical acceptance criteria.
- Showcase production backend practices; LLMs/RAG; agents/MCP; forecasting/ML; evaluation, security and observability.
- **Local Ollama** is the preferred inference provider. Provider abstraction is required; model selection is benchmarked, not assumed.
- This is a **portfolio** project, not a commercial product. Avoid payment, subscription and marketing scope.

## Non-negotiable principles
1. Calculations such as kWh differences, currency totals and tariff application are deterministic, testable domain code; the LLM never invents authoritative numbers.
2. Bills are untrusted input; AI extraction yields **proposed fields** requiring validation and an explicit confirmation step.
3. Historical tariffs are **effective-dated and source-backed**. Do not pretend a synthetic price is the current Dominican tariff.
4. Never place personal utility account numbers, full addresses or real bills in public repositories, screenshots or evaluation data.
5. No auto-execution of consequential agent actions; authorize and audit every write action.
6. Maintain a repeatable synthetic demo fixture and documented evaluation results.

## How to continue implementation
At the repository root, ask the implementation agent:

> Read `AGENTS.md`, `README.md`, `docs/PROGRESS.md`, and the implementation roadmap. Act as the architect and implementation engineer. Implement the next incomplete ticket within the current phase, including tests, validation, and documentation. Use the documented defaults and report any unresolved blocker.

## Documentation maintenance
Any changed requirement updates its PRD item, user story, impacted API contract, test, phase gate and ADR. Keep `docs/PROGRESS.md` updated after review. No claim of passing tests without actually running them.

## Phase 0 local development setup

Run these commands in PowerShell from the repository root. Python 3.13 is the
project target; `uv` manages the interpreter, virtual environment, and dependencies.

```powershell
# Keep downloaded packages and the managed interpreter inside ignored directories.
$env:UV_CACHE_DIR = Join-Path $PWD '.cache/uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PWD '.local-python'

# Download Python 3.13 without adding a global executable shortcut.
uv python install 3.13 --no-bin

# Resolve dependencies into uv.lock and install them into a local .venv.
uv sync

# Run the project interpreter and display its version and executable path.
uv run python -c "import sys; print(sys.version); print(sys.executable)"

# Verify that the test runner is installed in this environment.
uv run python -m pytest --version
```

The environment variables above apply to the current PowerShell session. Set them
again in a new terminal when using this repository-local interpreter location.
No virtual-environment activation is required with `uv run`.

`pyproject.toml` declares project metadata, the Python version range, development
tools, and tool configuration. `uv.lock` will record the resolved versions after
successful dependency resolution; it should be version-controlled. `.venv`,
`.cache`, and `.local-python` are generated locally and ignored.

The package starts at `backend/src/energyiq`. Its empty `__init__.py` identifies
the package. `consumption.py` calculates cumulative-reading differences using
Decimal inputs and rejects unsupported types, nonfinite values, negative values,
and decreasing readings. Its explicit local Decimal context returns an exact
result or raises an arithmetic error, independent of the caller's settings.
`observations.py`
calculates elapsed hours between strictly increasing, timezone-aware timestamps
with zero UTC offsets. Its `sort_observations` helper accepts timestamp/Decimal
pairs for one meter, validates UTC timestamps, and returns a chronological copy
without mutating the input collection. Equal timestamps and exact duplicates
remain in their original relative order for later Phase 1 validation. Unsupported
timestamp types and malformed observation pairs raise clear TypeError errors.
Tests live
in `backend/tests`. Pytest's configured
`pythonpath` makes the source package
importable during tests. There is no distributable-package build configuration yet.

Run `uv run python -m pytest`. The `-m` option runs pytest as a module through the
selected Python interpreter. If Windows denies writes to `.pytest_cache`, run
`uv run python -m pytest -q -p no:cacheprovider` to disable only the optional cache
for that invocation. The latest verified suite contains 254 passing tests.

`uv run ruff check backend` checks common code issues.
`uv run ruff format --check backend` checks formatting without changing files.
Ruff does not establish domain correctness; that is the purpose of behavioral
tests and review. See `docs/PROGRESS.md` for the last recorded checks,
remaining implementation gaps, and next task.

## Run the local consumption CLI

From the repository root in PowerShell:

```powershell
# Make the source package importable for this terminal session.
$env:PYTHONPATH = Join-Path $PWD 'backend/src'
uv run python -m energyiq
```

The source package is not installed as a distributable yet. Set `PYTHONPATH`
again in a new terminal; the pytest source-path configuration applies only to tests.
If the environment is already synchronized, `.venv/Scripts/python.exe -m energyiq`
also works with the same `PYTHONPATH` setting.

Example session with synthetic readings:

```text
Previous cumulative reading (kWh): 13007.10
Current cumulative reading (kWh): 13007.30
Consumption: 0.20 kWh
```

Use a decimal point without thousands separators. The CLI accepts surrounding
whitespace and valid Decimal exponent notation. Invalid, non-finite, negative,
decreasing, or unsupported arithmetic inputs produce a clear stderr error and
exit status 2. Incomplete input also returns 2; Ctrl+C returns 130. Successful
calculations return 0. Each invocation performs one calculation and stores no data.

Consumption arithmetic uses precision 28 with `Emin=-999999` and `Emax=999999`.
Results that would lose numeric precision, overflow, or underflow fail clearly;
the function never returns a silently rounded consumption value. Exact very small
results are permitted through `1e-1000026`. Ordinary fractional output such as
`0.20` is preserved. This computation policy is separate from the Phase 1
reading scale and bound. Direct Python callers
must supply Decimal objects, including for whole numbers; elapsed time helpers
require datetime objects with zero UTC offsets. See the
[hardening spec](docs/specs/0001-phase-zero-domain-hardening.md) for the contract.

## Phase 1 reading records

`energyiq.readings` provides immutable `Reading` and `MeterEvent` dataclasses.
They require UUID identities, explicit UTC instants, and enum values for source,
status, or event kind. Cumulative kWh is a finite nonnegative `Decimal` with at
most six meaningful fractional places and a maximum of
`999999999999.999999`. Validation does not round or alter the caller's Decimal
context. An optional original local date records provenance but never supplies
an inferred UTC instant. Event approval actor and time must appear together.
These records do not sort readings, reject duplicates, apply event boundaries,
or persist data. See the [P1-01 spec](docs/specs/0002-reading-meter-event-models.md).

`energyiq.readings.order_readings` accepts readings for one meter and returns an
immutable `ReadingOrderResult`. Its `ordered` tuple keeps every input occurrence
in timestamp order, with input order preserved at equal timestamps. Its
`conflicts` tuple contains one group for each repeated timestamp, including
original input indices and readings of every status. Invalid items and mixed
meters fail with the offending index. Callers must resolve nonempty conflicts
before using the result for interval calculations. The operation does not
mutate input, access storage, or calculate consumption. See the
[P1-02 spec](docs/specs/0003-reading-order-conflicts.md).

`energyiq.readings.compute_intervals` takes a conflict free `ReadingOrderResult`
and meter events. It returns one immutable interval for each adjacent pair of
nonvoided readings. A continuous pair of valid readings yields an exact Decimal
kWh difference. A flagged endpoint, unexplained decrease, or meter event in the
pair yields an invalid interval with no kWh value and an explicit reason. Events
at the current reading time belong to the new segment. Unapproved events and
unsupported rollover or calibration events also block consumption. The function
validates order and meter identity, consumes event input once, and performs no
storage or authorization. The caller must enforce meter ownership before
supplying source records. See the
[P1-03 spec](docs/specs/0004-reading-interval-boundaries/index.md).
