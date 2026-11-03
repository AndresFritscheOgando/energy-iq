# 0006. Property based invariant tests for reading and interval chains

**Date**: 2026-11-03
**Status**: Accepted

## Summary

This spec covers P1-05. It adds property based tests (tests that generate hundreds of random reading chains and check that a rule holds for every one) over the P1-02 ordering, P1-03 interval, and P1-04 window summary code. It adds Hypothesis, a test library, to the dev dependency group only, because its shrinking (automatically cutting a failing example down to the smallest one that still fails) is what makes a failure in a 40 reading chain debuggable. Default runs are fixed and reproducible. An opt in `deep` profile searches wider. No application behavior changes unless a property finds a real bug.

## Requirements

**User stories**:
- As the engineer, I want the ordering, interval, tiling, and additivity rules checked across many generated chains, so that a bug in a rare shape (a collision at a window bound, a 1 µs interval, an event on a reading instant) is found before Phase 2 exposes these numbers through an API.
- As the engineer, I want a failing property to report a small, reproducible example, so that I can turn it into a plain regression test.
- As a later reviewer, I want the default suite to stay deterministic and fast, so that a property test never fails without a code change.

**Acceptance criteria**:
- **AC-1 (dependency and profiles)**: `hypothesis` is in the `[dependency-groups] dev` list of `pyproject.toml` with a lower bound of `>=6.170` and is pinned in `uv.lock`. `[project] dependencies` stays empty. `backend/tests/conftest.py` registers two profiles and loads one chosen by `ENERGYIQ_HYPOTHESIS_PROFILE`. The default is `energyiq`: `max_examples=200`, `derandomize=True`, `database=None`, `deadline=None`, `print_blob=True`. The other is `deep`: `max_examples=2000`, `derandomize=False`, the default local example database, `deadline=None`, `print_blob=True`. An unknown profile name fails the test session at startup, and is never silently replaced by the default. `.hypothesis/` is in `.gitignore`. No health check is suppressed.
- **AC-2 (ordering stability)**: For every generated list of readings for one meter (timestamp collisions included, all three statuses), `order_readings` returns `ordered` as a permutation of the input (every occurrence kept, none changed), with nondecreasing `recorded_at`. Readings with equal `recorded_at` keep their input order. `conflicts` holds exactly one group per timestamp that occurs more than once, in ascending time. Each group lists every occurrence in ascending `input_index`, and each `entry.reading` is the input at that index. Ordering an already ordered result returns it unchanged. For inputs with distinct timestamps, any shuffle of the input gives the same `ordered` tuple. A single pass iterator gives the same result as the list.
- **AC-3 (interval boundary rules)**: For every generated conflict free chain and event list for one meter, `compute_intervals` returns one interval per consecutive pair of non voided readings (so the count is `max(0, non_voided − 1)`). Each interval's `start` and `end` are those readings' `recorded_at`, with the matching reading IDs, and consecutive intervals touch end to start. Each interval's `event_ids` are exactly the IDs of the events with `previous.recorded_at < effective_at <= current.recorded_at`, ordered by `effective_at` with ties in input order. Status and reason follow the spec 0004 precedence. With any events in the pair: `unapproved_event` if any is unapproved, else `unsupported_event` if any is `rollover` or `calibration`, else `meter_boundary`. With no events: `flagged_reading` if either endpoint is flagged, then `unexplained_decrease` if `current < previous`, else valid with `consumption_kwh == current − previous` exactly. A generated input with any timestamp collision raises `ValueError`.
- **AC-4 (exact window tiling)**: For every generated chain from AC-3 and every generated window, the `summarize_consumption` result satisfies the following. The segments (each measured interval as `[start, end)` plus each gap), sorted by start, begin at `window_start`, end at `window_end`, and each ends exactly where the next begins, with no hole and no overlap. `covered` equals the sum of measured durations, `uncovered` equals the sum of gap durations, and their sum equals the window length. Each measured interval is valid and lies fully inside the window. Every valid interval fully inside the window is measured. `measured_kwh` is the exact sum of their `consumption_kwh`. A `partial_interval` gap comes only from a valid interval that crosses a window bound. An `invalid_interval` gap comes only from an invalid interval, and carries its `reason` and `event_ids`. Each overlapping interval yields exactly one segment. `coverage_ratio` and `average_kwh_per_day` equal the exact rational value rounded once, half even, to 4 and 6 places. No value anywhere in the summary is a `float`.
- **AC-5 (additivity)**: For every generated chain and every generated set of cut points `t0 < t1 < … < tk` (k from 2 to 5), with intervals identified by `(previous_reading_id, current_reading_id)`, three things hold. First, no interval is measured in two pieces `[ti, ti+1)`. Second, the measured set of the whole window `[t0, tk)` is the disjoint union of the pieces' measured sets and the set X of valid intervals that lie inside `[t0, tk)` and strictly cross at least one interior cut. Third, `measured_kwh(whole) == Σ measured_kwh(pieces) + Σ kWh(X)` and `covered(whole) == Σ covered(pieces) + Σ duration(X)` hold exactly. For k = 2 this is the adjacent windows rule `[a, b)` plus `[b, c)`.
- **AC-6 (generators cover the boundary shapes)**: The strategies draw kWh from the full validated domain (`0` to `999999999999.999999`, up to 6 fractional places) and UTC microsecond timestamps. They build times from small steps on a coarse grid, so that collisions, 1 µs intervals, events exactly on reading instants, and window bounds equal to (or 1 µs from) interval boundaries are generated regularly. They also generate windows entirely before, entirely after, and fully covering the data, plus empty chains. Every strategy builds valid model records directly (no `assume` or `filter` that rejects most draws), so no health check fires.
- **AC-7 (bug handling and budget)**: The new property file passes under the `energyiq` profile, and adds no more than 15 seconds to the full suite on the development machine (measured and recorded in PROGRESS). If a property finds a real defect, the source is fixed within this ticket and the shrunk case is pinned twice: as an `@example` on the property and as a plain unit test in the matching existing test file. A fix that would change a documented contract in specs 0003 to 0005 stops for the engineer's decision instead. The full suite, `ruff check .`, `ruff format --check .`, and strict `pyright` (which covers tests) pass.

## Decision

**Chosen option**: Option 1: Hypothesis in the dev group, with a fixed default profile and an opt in deep profile

Add Hypothesis as a dev only dependency and write one property test module whose strategies build real `Reading` and `MeterEvent` records and push them through the real `order_readings`, `compute_intervals`, and `summarize_consumption` pipeline.

**Decisions made in this spec** (each a call the build would otherwise invent):
- **Hypothesis is justified as a dev only dependency.** These invariants live in rare shapes, and a seeded random harness without shrinking turns every failure into a hand bisection of a long chain. Runner up: stdlib `random.Random(seed)` generators, with no new package but no shrinking. Full reasoning is in [rationale.md](rationale.md).
- **Profile selection uses a project env var, `ENERGYIQ_HYPOTHESIS_PROFILE`, read in `backend/tests/conftest.py`**, which calls `settings.load_profile(...)` explicitly. Hypothesis auto activates its own `ci` profile when a `CI` variable is set, so an explicit load keeps local and CI runs identical. Runner up: the plugin's command line option, which the docs check did not confirm, and which is easy to forget on the command line.
- **`deadline=None` in both profiles.** Per example timing on a Windows laptop varies a lot, and a timing failure here says nothing about correctness. Runner up: the 200 ms default, which risks flaky failures.
- **`print_blob=True`**, so a failure prints a `@reproduce_failure` line you can paste in to replay it.
- **One test module, `backend/tests/test_reading_properties.py`**, holds the strategies and the properties. With `--import-mode=importlib`, sibling helper modules are awkward to import, and one file keeps the generators next to the rules they feed. Runner up: a `backend/tests/strategies/` helper package on `pythonpath`, worth it only if a second property file appears.
- **Rule checks, not a reference model**, for AC-3. Each property states the spec 0004 rule for one pair directly. A second implementation of `compute_intervals` would duplicate the algorithm and could share its mistakes.
- **Chains come from the real pipeline.** The tiling and additivity properties build `ConsumptionInterval` chains with `compute_intervals`, never by hand, so they only ever test chains that the system can actually produce. That covers every `IntervalReason`.
- **No pytest marker.** The property tests run in the default `pytest` invocation within the AC-7 budget. A marker would let them quietly drop out of routine runs.
- **No health check suppression.** If a strategy trips `filter_too_much` or `too_slow`, the strategy gets fixed instead.

## Feature design

**Data model sketch**: none. No persistence, schema, or new domain record. The test only data shapes are:

| Strategy | Produces | Rules |
|---|---|---|
| `meter_ids` | `UUID` | one per generated scenario. A second, distinct meter only appears in the mixed meter checks |
| `kwh_values` | `Decimal` | `0` to `999999999999.999999`, 0 to 6 fractional places, finite |
| `instants` | UTC `datetime` | `base + Σ steps`, where `base` is a fixed UTC epoch in 2026 and each step is drawn from `{0, 1 µs, 1 s, 1 h, 1 day, 36 h, arbitrary µs up to 60 days}`. A zero step creates a collision |
| `reading_lists` | `list[Reading]` | 0 to 30 readings, one meter, any status, input order shuffled, collisions allowed (for AC-2) |
| `reading_chains` | `ReadingOrderResult` with no conflicts | 0 to 30 readings with strictly increasing times. Values mostly nondecreasing with occasional decreases. Statuses weighted toward `valid` |
| `event_lists` | `list[MeterEvent]` | 0 to 6 events for the chain's meter, any `MeterEventType`, approved or not, `effective_at` drawn from reading instants, 1 µs from them, or between them, and before or after the data |
| `windows` | `(start, end)` | bounds drawn from interval boundaries, those boundaries plus or minus 1 µs, and arbitrary instants within, before, and after the data span, with `end > start` built by construction |
| `cut_points` | `tuple[datetime, ...]` | 3 to 6 strictly increasing instants from the same mix as `windows` |

**State transitions**: none.

**API surface** (test only; no application interface changes):

| Item | Kind | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `backend/tests/conftest.py` | pytest config | `ENERGYIQ_HYPOTHESIS_PROFILE` (optional, `energyiq` or `deep`) | the loaded Hypothesis profile | none | unknown profile name fails session startup (`InvalidArgument` from `load_profile`) |
| `backend/tests/test_reading_properties.py` | property tests | the strategies above | pass or a shrunk failing example | none | assertion failure with a reproduce blob |
| `pyproject.toml` / `uv.lock` | dependency | `hypothesis>=6.170` (dev group) | locked version | none | none |

**Value sourcing**:

| Action | Value produced / checked | Source |
|---|---|---|
| profile load | profile name | env var `ENERGYIQ_HYPOTHESIS_PROFILE`, default `energyiq` (decided here) |
| profile load | example count, derandomize, database, deadline, print blob | the two profile definitions in AC-1 (decided here) |
| AC-2 | expected order and conflict groups | derived in the test from the input list, using its indices and a grouping by `recorded_at` |
| AC-3 | the expected pair set | derived: consecutive non voided readings of the generated chain |
| AC-3 | the expected `event_ids` per pair | derived: the generated events filtered by `previous < effective_at <= current`, stably sorted by `effective_at` |
| AC-3 | the expected status and reason | the spec 0004 precedence restated in the test |
| AC-4 | the expected measured set and kWh | derived: valid intervals with `window_start <= start` and `end <= window_end`, summed under `exact_kwh_context()` |
| AC-4 | the expected ratio and average | derived: `Fraction` from integer microseconds, rounded once, half even (the spec 0005 rule), using a test local helper, not the private `_round_once` |
| AC-5 | the crossing set X | derived: valid intervals inside `[t0, tk)` whose open span `(start, end)` contains an interior cut point |
| AC-5 | interval identity | `(previous_reading_id, current_reading_id)` from the P1-03 record |
| AC-7 | added runtime | measured with `pytest --durations` on the development machine, recorded in PROGRESS |

**Key invariants** (the properties themselves): the five rule families in AC-2 to AC-5. The test also never uses binary floats for expected values, never builds a `ConsumptionInterval` by hand for AC-4 or AC-5, and never calls a private `energyiq` function.

**Security model**: tests only, with no I/O, network, model calls, or real data. Every UUID and value is synthetic and generated. Hypothesis is a dev dependency only, so it never reaches the application runtime. The deep profile's local example database (`.hypothesis/`) holds only generated synthetic values and is git ignored. The new package comes from PyPI through `uv` with a locked hash.

**Configuration required**:
- `ENERGYIQ_HYPOTHESIS_PROFILE`: optional, tests only. `energyiq` (default, fixed and reproducible) or `deep` (random, 2000 examples). Never needed by the application.

**Critical test scenarios**:
- Happy path: the default `uv run pytest -q -p no:cacheprovider` run executes every property at 200 examples, deterministically, and passes. Verifies **AC-1** through **AC-5**.
- Repeatability: two consecutive default runs try the same examples (derandomized) and write no `.hypothesis/` database. Verifies **AC-1**.
- Deep run: `ENERGYIQ_HYPOTHESIS_PROFILE=deep uv run pytest backend/tests/test_reading_properties.py` runs 2000 random examples per property. Verifies **AC-1**.
- Wrong profile: `ENERGYIQ_HYPOTHESIS_PROFILE=nope` fails at session startup. Verifies **AC-1**.
- Mutation sanity (done once by hand, not committed): temporarily change `summarize_consumption` to measure an interval that touches `window_start`, and change the ordering sort to be unstable. The tiling, additivity, and ordering properties must each fail with a small shrunk example. Then revert. Verifies **AC-4**, **AC-5**, **AC-2**, **AC-6**.
- Budget: `pytest --durations=0` shows the property file at or under 15 seconds total. Verifies **AC-7**.
- Auth/permission: not applicable (no data access). The mixed meter rejection is already covered by the unit tests from specs 0003 and 0005.

## Build plan

No build approach is recorded for this project, so this assumes Tracer Bullet: first one thin property running end to end through the real pipeline, then more properties. No schema or migration is involved.

1. [x] Run `uv add --dev "hypothesis>=6.170"`, confirm `uv.lock` updates and `[project] dependencies` stays empty, and record the resolved version. Add `.hypothesis/` to `.gitignore`. Add `backend/tests/conftest.py` with the two profiles and the env var selection. Satisfies **AC-1**.
2. [x] Add `backend/tests/test_reading_properties.py` with the `meter_ids`, `kwh_values`, `instants`, and `reading_lists` strategies and the AC-2 ordering properties. This is the thin end to end thread. Confirm it runs under strict Pyright. Satisfies **AC-2**, **AC-6**.
3. [x] Add `reading_chains` and `event_lists` and the AC-3 interval rule properties, including the collision raises case. Satisfies **AC-3**, **AC-6**.
4. [x] Add `windows` and the AC-4 tiling property, including the no float walk over the summary, and the ratio and average check through a test local single rounding helper. Satisfies **AC-4**, **AC-6**.
5. [x] Add `cut_points` and the AC-5 additivity property for k = 2 to 5. Satisfies **AC-5**, **AC-6**.
6. [x] Run the mutation sanity check by hand and revert it. Run the deep profile once. Fix any real defect per AC-7 and pin it. Measure the added runtime. Satisfies **AC-6**, **AC-7**.
7. [x] Update `docs/07-TESTING-EVALUATIONS.md` (property tests and profiles), `docs/03-TECH-STACK.md` (Hypothesis in the test row), the roadmap P1-05 entry, the README test section if it lists tools, and `docs/PROGRESS.md`. Run the full suite, `ruff check .`, `ruff format --check .`, and `pyright`. Satisfies **AC-1** through **AC-7**.

## Consequences

**Positive**:
- The tiling and additivity rules that P1-04 promised are now checked across thousands of shapes, not 12 hand built summaries.
- Failures shrink to a minimal chain and print a replay line, so a bug costs minutes, not an afternoon.
- The default suite stays deterministic, so a red run always means a code change.

**Negative / tradeoffs**:
- One new dev dependency to keep updated. Hypothesis releases often, and an upgrade can change which examples a derandomized run tries, so a new failure can appear on upgrade with no code change. Such a failure is still a real bug, but the upgrade has to be handled as its own small change.
- A derandomized default only ever searches one fixed set of examples. Wider search happens only when someone runs `deep`.
- Around 15 seconds added to every full test run.
- The test restates the spec 0004 precedence and the spec 0005 rounding rule. If those contracts change, these properties change with them.

**Neutral**:
- It sets the pattern for later phases: property tests sit next to the unit tests, use real domain records, and never mock the code under test.
- It adds the first `conftest.py` to the test tree.

## Follow-up

- [ ] Specs 0001 to 0004 are still missing from disk (see spec 0005 Follow-up), and `/docs` is still git ignored. This spec needs explicit force staging too.
- [ ] If a CI pipeline is added later, it should run the default profile on every push and could run `deep` on a schedule.
- [ ] If Phase 2 adds a second property test file (for example over API request schemas), move the strategies into a shared helper package then, not now.

## Rationale

Reasoning, options, and references: see [rationale.md](rationale.md).
