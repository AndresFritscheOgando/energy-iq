# 0005. Time normalized consumption rates and window coverage gaps

**Date**: 2026-11-03
**Status**: Accepted

## Summary

This spec covers P1-04. It turns the P1-03 interval results into usage rates (kWh per day, based on the real time between readings) and into a summary for a time window you ask for. The summary says how much energy was actually measured, how much of the window that measurement covers, and exactly where and why data is missing. Nothing is estimated: a span with no trustworthy measurement is reported as a gap, never filled in. The work is pure Python domain code with no database, API, or new dependency.

## Requirements

**User stories**:
- As a resident, I want my usage as kWh per day for each reading interval, so I can compare periods of different lengths.
- As a resident, I want a usage summary for a date range that shows how much of the range is truly measured and where data is missing, so a gap is never mistaken for zero usage.
- As a later system component (API, chart, reconciliation), I want one deterministic, exact normalization and coverage contract, so every surface reports the same numbers.

**Acceptance criteria**:
- **AC-1**: `normalize_intervals` returns one `NormalizedInterval` per input interval, in input order. Each has `duration = end − start`. A valid interval has `kwh_per_day = consumption_kwh × 86400 ÷ elapsed seconds`, computed from the exact rational value and rounded once to 6 fractional places with half even rounding (example: 10 kWh over 36 hours gives `Decimal("6.666667")`). An invalid interval has `kwh_per_day = None`. A valid interval with 0 kWh has rate `Decimal("0.000000")` and counts as measured, not missing.
- **AC-2**: Both functions reject bad interval input with indexed errors: a non `ConsumptionInterval` item raises `TypeError`, and intervals from more than one meter, or intervals where any `start` differs from the previous interval's `end` (a hole or an overlap), raise `ValueError`. A single pass iterator is consumed only once. Input records are never modified.
- **AC-3**: `summarize_consumption` rejects bad arguments: a `meter_id` that is not a UUID raises `TypeError`, an interval whose meter differs from `meter_id` raises an indexed `ValueError`, window bounds that are not zero offset UTC datetimes raise the existing UTC validation errors, and `window_end <= window_start` raises `ValueError`.
- **AC-4**: The summary's `measured_kwh` is the exact Decimal sum of `consumption_kwh` for valid intervals lying fully inside the half open window `[window_start, window_end)`, and `measured_intervals` lists exactly those intervals as `NormalizedInterval` records in time order. With none, `measured_kwh` is `Decimal("0")` and the tuple is empty. An interval that only touches a window bound (its `end == window_start` or its `start == window_end`) does not overlap the window.
- **AC-5**: The measured intervals and the gaps together cover the window exactly: they are in time order, never overlap, and leave no hole. `covered` equals the sum of measured interval durations, `uncovered` equals the sum of gap durations, and `covered + uncovered == window_end − window_start`.
- **AC-6**: Each gap is trimmed to the window and has one reason: `before_first_reading` (window time before the first interval starts), `after_last_reading` (window time after the last interval ends), `no_intervals` (the whole window, when there are no intervals at all), `partial_interval` (the in window part of a valid interval that crosses a window bound, with its reading IDs), or `invalid_interval` (the in window part of an invalid interval, with its reading IDs, its `IntervalReason` as `interval_reason`, and its `event_ids`). An invalid interval that crosses a bound is still `invalid_interval`. Each gap traces to at most one interval.
- **AC-7**: `coverage_ratio = covered ÷ window length`, rounded once to 4 fractional places with half even rounding. `average_kwh_per_day = measured_kwh × 86400 ÷ covered seconds`, rounded once to 6 places with half even rounding, or `None` when `covered` is zero. Missing data never raises: a window with no intervals, or one entirely before or after the data, returns a summary with zero measured kWh, zero coverage, `None` average, and one gap covering the whole window.
- **AC-8**: Nothing is estimated or interpolated. A partial interval's kWh never enters `measured_kwh` or the average, and no value anywhere in the results is a binary float. Durations are `timedelta`, and kWh, rates, and ratios are `Decimal`.

## Decision

**Chosen option**: Option 1: Per interval rates plus an exact window summary with typed gaps

Add a pure `energyiq.readings.normalization` module with `normalize_intervals` and `summarize_consumption`. They return frozen records that report measured kWh, kWh per day rates, exact coverage, and one typed gap per cause of missing data, and they never estimate.

**Decisions made in this spec** (each a call the build would otherwise invent):
- **Single rounding from the exact rational value.** Compute rates and ratios as `fractions.Fraction` (standard library, exact rational numbers) from integer microseconds, round once to the target scale with half even rounding, then build the `Decimal` from the rounded integer (`Decimal(n).scaleb(-places)`). This is never off by one in a halfway case and never hits a precision trap. Runner up: Decimal division in a fixed precision context followed by `quantize`, which rounds twice and needs extra care around precision limits.
- **"Per day" means 86,400 seconds of elapsed UTC time**, not a local calendar day. Elapsed time comes from `timedelta` as exact integer microseconds (`(days × 86400 + seconds) × 10⁶ + microseconds`). The float `elapsed_hours` helper is not used and stays unchanged. Runner up: local calendar days, which belongs to a later presentation spec.
- **`measured_kwh` addition** uses the same exact arithmetic policy as `calculate_consumption` (precision 28, `Inexact` trapped), so a sum that cannot be held exactly raises a `DecimalException` instead of rounding. Runner up: unbounded `Fraction` addition, which hides the scale contract.
- **`normalize_intervals` validates the same chain rules as the summary** (types, one meter, intervals that touch end to start), with the meter taken from the first interval. That way neither function accepts a chain the other would reject. Runner up: validating only in the summary, which lets broken chains through to rate callers.
- **`measured_intervals` holds valid intervals only.** Invalid intervals appear only as gaps, so the measured list and the gap list never describe the same time twice.
- **Empty input to `normalize_intervals` returns an empty tuple.**

## Feature design

**Data model sketch** (in memory frozen, slotted dataclasses with runtime validation; no persistence):

| Record | Field | Type | Required | Rule |
|---|---|---|---|---|
| `NormalizedInterval` | `interval` | `ConsumptionInterval` | yes | P1-03 record, unchanged |
| | `duration` | `timedelta` | yes | equals `interval.end − interval.start`, always more than zero |
| | `kwh_per_day` | `Decimal \| None` | valid only | valid: finite, ≥ 0, exactly 6 fractional places. Invalid: `None` |
| `GapReason` (`StrEnum`) | | | | `before_first_reading`, `after_last_reading`, `no_intervals`, `partial_interval`, `invalid_interval` |
| `ConsumptionGap` | `start`, `end` | UTC `datetime` | yes | `end > start`, both inside the window |
| | `duration` | `timedelta` | yes | equals `end − start` |
| | `reason` | `GapReason` | yes | |
| | `interval_reason` | `IntervalReason \| None` | invalid only | set if and only if `reason = invalid_interval` |
| | `previous_reading_id`, `current_reading_id` | `UUID \| None` | interval gaps | both set if and only if the reason is `partial_interval` or `invalid_interval` |
| | `event_ids` | `tuple[UUID, ...]` | yes | the invalid interval's events, otherwise `()` |
| `ConsumptionWindowSummary` | `meter_id` | `UUID` | yes | the caller's argument |
| | `window_start`, `window_end` | UTC `datetime` | yes | half open, `window_end > window_start` |
| | `measured_kwh` | `Decimal` | yes | finite, ≥ 0 |
| | `covered`, `uncovered` | `timedelta` | yes | each ≥ 0, sum equals the window length |
| | `coverage_ratio` | `Decimal` | yes | from 0 to 1, exactly 4 fractional places |
| | `average_kwh_per_day` | `Decimal \| None` | yes | `None` if and only if `covered` is zero, else 6 places |
| | `measured_intervals` | `tuple[NormalizedInterval, ...]` | yes | valid, fully inside the window, time ordered |
| | `gaps` | `tuple[ConsumptionGap, ...]` | yes | time ordered |

Relationships: one summary has zero or more measured intervals and zero or more gaps. Each `NormalizedInterval` wraps exactly one `ConsumptionInterval`, and each gap refers to at most one interval through its reading IDs. Records validate their own field rules in `__post_init__`, following the P1-03 pattern. The summary's tiling invariant is guaranteed by construction in the function and checked in tests. The record does not recheck it.

**State transitions**: none. All records are derived, immutable, and never stored.

**API surface** (Python functions exported from `energyiq.readings`):

| Function | Kind | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `normalize_intervals(intervals)` | pure function | `intervals: Iterable[ConsumptionInterval]` (req) | `tuple[NormalizedInterval, ...]` in input order | none (in process, no data access) | `TypeError` indexed item type; `ValueError` indexed mixed meter, hole, or overlap |
| `summarize_consumption(intervals, meter_id, window_start, window_end)` | pure function | `intervals: Iterable[ConsumptionInterval]` (req), `meter_id: UUID` (req), `window_start: datetime` (req, UTC), `window_end: datetime` (req, UTC) | `ConsumptionWindowSummary` | none (in process, no data access) | `TypeError` non UUID meter or bad item; `ValueError` indexed meter mismatch, hole, overlap; `ValueError` non UTC or empty window |

**Window summary algorithm** (deterministic, one pass, O(n)):
1. Validate the arguments and materialize the iterable once. Validate the chain (AC-2, AC-3).
2. No intervals: one `no_intervals` gap over the whole window.
3. Otherwise the data span is `[first.start, last.end)`. Window time before `first.start` becomes one `before_first_reading` gap, and window time at or after `last.end` becomes one `after_last_reading` gap (each trimmed, and only if not empty).
4. For each interval with `start < window_end` and `end > window_start`: if it is valid and fully inside, it is measured. If it is valid and crosses a bound, its in window part is a `partial_interval` gap. If it is invalid, its in window part is an `invalid_interval` gap.
5. Gaps are emitted in time order. Covered, uncovered, the ratio, and the average are computed from integer microseconds with single rounding.

**Value sourcing**:

| Action | Value produced / displayed | Source |
|---|---|---|
| normalize | `duration` | derived: `interval.end − interval.start` (P1-03 record) |
| normalize | `kwh_per_day` | derived: `Fraction(consumption_kwh) × 86_400_000_000 ÷ duration_µs`, rounded once to 6 places, half even (decided here) |
| normalize | the chain's meter | derived: `intervals[0].meter_id` |
| summarize | `meter_id` | input param, matched against every interval |
| summarize | `window_start`, `window_end` | input params (UTC, half open) |
| summarize | `measured_kwh` | derived: exact sum of `consumption_kwh` from fully contained valid intervals, under the precision 28 `Inexact` trapped policy (decided here) |
| summarize | `measured_intervals` | derived: `normalize_intervals` output filtered to valid, fully contained intervals |
| summarize | gap `start` / `end` | derived: interval or data span bounds trimmed with `max(…, window_start)` and `min(…, window_end)` |
| summarize | gap `reason` | derived: the rule in algorithm steps 2 to 4 |
| summarize | gap `interval_reason`, `event_ids`, reading IDs | copied from the source `ConsumptionInterval` |
| summarize | `covered`, `uncovered` | derived: sum of measured durations, and sum of gap durations |
| summarize | `coverage_ratio` | derived: `Fraction(covered_µs, window_µs)`, rounded once to 4 places, half even (decided here) |
| summarize | `average_kwh_per_day` | derived: `Fraction(measured_kwh) × 86_400_000_000 ÷ covered_µs`, rounded once to 6 places, half even, or `None` when `covered_µs == 0` |

**Key invariants**:
- Measured intervals plus gaps cover `[window_start, window_end)` exactly, in time order, with no overlap or hole.
- `covered + uncovered == window_end − window_start`. `covered` is zero exactly when `measured_intervals` is empty.
- `measured_kwh` includes only valid intervals that sit fully inside the window. No partial or invalid kWh is ever counted.
- Every Decimal rate or ratio is rounded exactly once, half even, at the declared scale (6 places for rates, 4 for the ratio).
- The input chain belongs to one meter and touches end to start. Anything else is rejected, never repaired.
- No float, no interpolation, no fabricated reading.

**Security model**: pure in process functions with no I/O, persistence, network access, or model calls. They do not authorize anything. Ownership is enforced by the Phase 2 caller that loads one owned meter's readings before calling `compute_intervals` and then this module. The required `meter_id` check stops a caller from mixing another meter's intervals into a summary. Tests use synthetic UUIDs and values only, never real meter or account data.

**Configuration required**: none. No environment variables, credentials, or dependencies (`fractions` is standard library).

**Critical test scenarios**:
- Happy path: readings every 36 hours with 10 kWh each over a window holding three full intervals give `measured_kwh = 30`, a rate of `6.666667` per interval, a full coverage ratio of `1.0000` when the window matches the data span, and no gaps. Verifies **AC-1**, **AC-4**, **AC-5**, **AC-7**.
- Rounding: halfway cases (rates whose seventh decimal decides a tie) round half even. Ratio examples such as 1/3 give `0.3333` and 2/3 give `0.6667`. Verifies **AC-1**, **AC-7**.
- Zero usage: a valid 0 kWh interval has rate `0.000000`, counts as covered, and creates no gap. Verifies **AC-1**, **AC-5**.
- Gap characterization: one window that starts before the first reading, cuts a valid interval at its end, and contains a meter event interval and a flagged interval gives gaps `before_first_reading`, `invalid_interval` (with `meter_boundary` and event IDs), `invalid_interval` (`flagged_reading`), and `partial_interval`, all trimmed and tiling exactly. Verifies **AC-5**, **AC-6**, **AC-8**.
- Bound touching: an interval ending exactly at `window_start` is ignored, and an interval exactly equal to the window is measured. Verifies **AC-4**.
- No data: empty intervals, a window entirely before the data, and a window entirely after it each return zero coverage, `None` average, and one whole window gap with the right reason. Verifies **AC-7**.
- Failure case: a chain with a removed middle interval (a hole), an overlap, mixed meters, a wrong item type, a non UTC bound, an empty window, and a `meter_id` mismatch each raise the specified indexed error. A generator input is consumed once. Verifies **AC-2**, **AC-3**.
- Auth/permission: not applicable in process. The meter mismatch case (an interval from another meter) is rejected with an indexed `ValueError`. Verifies **AC-3**.
- No float: a recursive type check over a summary confirms no `float` value appears. Verifies **AC-8**.

## Build plan

No build approach is recorded for this project, so this assumes Tracer Bullet: first a thin working path from P1-03 output to a rate, then thicker coverage. No schema or migration is involved.

1. [x] Add `backend/src/energyiq/readings/normalization.py` with the `NormalizedInterval` record, the shared chain validation (item type, one meter, touching chain, single pass materialization), the exact microsecond duration helper, and the single rounding `Fraction` to `Decimal` helper. Implement `normalize_intervals`, with tests for rates, rounding, zero usage, invalid intervals, and chain errors. Satisfies **AC-1**, **AC-2**, **AC-8**.
2. [x] Add `GapReason`, `ConsumptionGap`, and `ConsumptionWindowSummary` with field validation. Implement `summarize_consumption` argument validation and the measured path (fully contained valid intervals, `measured_kwh`, `covered`, ratio, average), with happy path and bound touching tests. Satisfies **AC-3**, **AC-4**, **AC-7**.
3. [x] Implement gap characterization (before and after the data, no intervals, partial, invalid with trimming), plus a tiling invariant helper used across the tests, the mixed gap scenario, and the no data scenarios. Satisfies **AC-5**, **AC-6**, **AC-7**, **AC-8**.
4. [x] Export the new names from `energyiq.readings.__init__`. Update `docs/04-DATA-MODEL-API.md` (the P1-04 contract line), the roadmap P1-04 entry, the README module table, and `docs/PROGRESS.md`. Run the full pytest suite, `ruff check .`, `ruff format --check .`, and `pyright`. Satisfies **AC-1** through **AC-8** (contract documentation and verification).

## Consequences

**Positive**:
- One exact, tested contract for rates and coverage that the Phase 2 consumption endpoint and the Phase 3 chart can expose directly.
- Gaps are first class and traceable to readings and events, so "missing" can never be shown as "zero".
- Summaries for adjacent windows never double count energy.

**Negative / tradeoffs**:
- Windows that do not line up with reading times lose their edge intervals, so reported coverage and measured kWh can be well below what users expect from frequent readings. The UI will need to explain partial interval gaps.
- No calendar day view yet. A daily chart needs a later, explicitly estimated allocation spec.
- Strict chain validation means callers must pass the complete `compute_intervals` output, so a filtered list fails loudly instead of degrading.
- Two rounding scales (6 and 4 places) are now part of the public contract, and changing them later breaks consumers.

**Neutral**:
- Introduces `fractions.Fraction` as the pattern for exact division before a single rounding. Future rate or ratio code should reuse the helper rather than `Decimal` division.
- `elapsed_hours` (float) remains for the Phase 0 CLI only and is not used by this module.
- Average rate is defined over covered time, not window time. Consumers must not multiply it by the window length to claim a total.

## Follow-up

- [ ] The `docs/specs/` folder was missing from disk on 2026-11-03. Specs 0001 and 0002 show as deleted in git (recoverable with `git restore docs/specs`), while specs 0003 and 0004 were never committed because of the `/docs` ignore rule and may be lost. `PROGRESS.md`, the roadmap, and the README still link to them. Recover or rewrite them before the next commit, and decide whether `/docs` should stay ignored. This spec is also ignored by that rule and needs explicit force staging.
- [x] Spec 0011 child 0002 chose measured interval rates on a real time axis, rather than estimated calendar day totals. Range boundaries use the property's timezone. Partial intervals are shown as named gaps with a longer range suggestion. A calendar day allocation remains a separate future feature if needed.
- [ ] P1-05 property based tests should cover the tiling invariant and additivity (summaries of adjacent windows never count the same interval twice) with generated chains.
- [ ] Open decision 4 (exact timestamp versus local date only readings) is still unresolved. Date only readings will need a conversion policy before they reach `compute_intervals`, and this spec assumes UTC instants.

## Decision record

The context, options considered, and reasoning behind this decision are in [rationale.md](rationale.md). Verification steps are in [verify.md](verify.md).
