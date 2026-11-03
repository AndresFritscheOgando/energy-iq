# Meter Semantics, Discontinuity Rules, and Operational Trade Offs

**Status:** Phase 1 reference, written for P1-06 under [spec 0007](specs/0007-meter-semantics-discontinuity-rules/index.md).
**Code:** `backend/src/energyiq/readings/` (public API in `energyiq.readings`).
**Examples test:** `backend/tests/test_meter_semantics_examples.py`.

## Purpose

This document is the one place that says what a meter reading means in EnergyIQ, when a kWh value is known, and when it must stay unknown. Phase 2 (API and database), Phase 3 (UI), and Phase 4 (bill reconciliation) build on these rules instead of inventing their own.

Three ideas carry everything below:

1. A reading is the running total shown on the meter register (cumulative kWh).
2. Consumption only exists between two readings with no break between them.
3. Every break is reported with a reason. Nothing is estimated, prorated, or guessed around.

Rules marked **decided, applied in Phase N** are agreed design that the code does not enforce yet. Every other rule here is enforced by the current code, and each worked example is checked by a test.

## Cumulative readings

A `Reading` records one cumulative register value for one meter at one exact UTC instant.

- **Value:** `cumulative_kwh` is a `Decimal`, finite, from `0` to `999999999999.999999`, with at most 6 meaningful fractional places. It is never rounded. Floats, negatives, infinities, and `NaN` are rejected when the record is created (`readings/models.py`, `_validate_kwh`).
- **Consumption:** the kWh of an interval is the exact difference `current − previous` of two consecutive non voided readings in one unbroken segment, computed under a fixed exact `Decimal` context that raises instead of rounding (`consumption.calculate_consumption`).
- **No use is valid:** two equal values give a valid interval of exactly `0` kWh (example E2).
- **A reading is not a bill.** A reading is an observation at an instant. A bill covers a period and is reconciled against readings later (Phase 4).

## Incremental readings

Incremental data reports kWh used **per period**, not a running total. Examples: the billed kWh for a bill period, or a smart meter export of kWh per 15 minute interval.

The rule: **incremental data is never turned into synthetic cumulative readings.** A running sum would need an invented starting value and would hide where each number came from.

- In Phase 4, a bill period kWh is **compared against** a measured window summary (`summarize_consumption`), never merged into the reading chain.
- A separate incremental data type is future work. It is not designed here.

## Time and ordering

- **Instants are UTC.** `recorded_at` must be an aware datetime with a zero UTC offset. The UI shows local time in `America/Santo_Domingo` by default.
- **Stable order:** `order_readings` sorts one meter's readings by `recorded_at`, keeps input order for equal instants, and never drops or changes a reading (`readings/ordering.py`).
- **Conflicts:** two or more readings at the same instant form a `ReadingTimestampConflict`, whatever their status. `compute_intervals` refuses the **whole chain** while any conflict remains, so a person must resolve it first.

### Date only readings (decided, applied in Phase 2, P2-04)

The domain keeps requiring an exact UTC instant. When a person enters a reading with a date but no time, the API boundary in P2-04 converts it:

- `recorded_at` becomes **12:00 local time in `America/Santo_Domingo` on that date**, which is always **16:00 UTC** (the zone is UTC−4 all year, with no daylight saving time).
- `original_local_date` keeps the date the person typed, as provenance.
- Two date only readings on the same local date, or a date only reading and a timestamped reading at exactly that instant, form a timestamp conflict and go through the P1-02 conflict flow (example E13).

Noon was chosen because it is the time least likely to sort out of order against a same day timestamped reading. It can still sort wrong against an afternoon reading on the same day; the order is deterministic, but not always the real one.

## Discontinuity rules

`compute_intervals` takes a conflict free ordered chain plus the meter events and returns one `ConsumptionInterval` per consecutive pair of non voided readings (`readings/intervals.py`).

| Case | Condition on the pair | Status | Reason | kWh |
|---|---|---|---|---|
| Valid | no event, neither endpoint flagged, `current ≥ previous` | `valid` | none | exact difference |
| Unapproved event | at least one event in the pair is not approved | `invalid` | `unapproved_event` | `None` |
| Unsupported event | all events approved, and at least one is `rollover` or `calibration` | `invalid` | `unsupported_event` | `None` |
| Meter boundary | all events approved, all are `installed`, `reset`, or `replaced` | `invalid` | `meter_boundary` | `None` |
| Flagged reading | no event, and either endpoint has status `flagged` | `invalid` | `flagged_reading` | `None` |
| Unexplained decrease | no event, no flag, `current < previous` | `invalid` | `unexplained_decrease` | `None` |

**Precedence**, exactly as the code applies it:

1. Any event in the pair decides first: `unapproved_event` if any event is unapproved, else `unsupported_event` if any is `rollover` or `calibration`, else `meter_boundary`. Event reasons carry the event IDs.
2. Else a flagged endpoint gives `flagged_reading`.
3. Else a decrease gives `unexplained_decrease`.
4. Else the pair is valid.

So an approved reset that explains a drop wins over the drop (E5), and an approved rollover still blocks kWh even though it explains the drop (E7).

**Event timing:** an event belongs to the pair where `previous.recorded_at < effective_at <= current.recorded_at`. A reading taken at the event instant is therefore the **first reading of the new segment**: the pair ending at it is the boundary, and the next pair is measured normally (E5).

**Voided and flagged readings behave differently:**

- A **voided** reading is skipped. The pair bridges over it, from the reading before to the reading after (E10).
- A **flagged** reading is a barrier. Both pairs that touch it are invalid with `flagged_reading` (E9). Flagging keeps the reading visible for review; voiding removes it from the calculation.

## Meter events

| Event type | Today | Planned direction |
|---|---|---|
| `installed` | approved gives `meter_boundary` | unchanged; also marks the first reading of a replacement meter (ADR-006) |
| `reset` | approved gives `meter_boundary` | unchanged |
| `replaced` | approved gives `meter_boundary` | stays supported for data recorded under one meter ID; from Phase 2 a replacement creates a new Meter record (below) |
| `calibration` | always `unsupported_event` | stays that way: calibration is an accuracy adjustment, never a source of kWh |
| `rollover` | always `unsupported_event` | supported once the Meter stores its register digit count (below) |

An unapproved event of any type gives `unapproved_event` until a person approves it.

### Rollover (decided, applied when the Meter stores its digit count)

A mechanical register with `digits` digits rolls from `10^digits − 1` back to `0`. Once the Meter stores its register digit count (designed in a Phase 2 spec), the rule becomes:

`kWh = (10^digits − previous) + current`

valid only for an **approved** rollover event, and only when the result is below `10^digits`. Until then no rollover pair gets kWh, even when the value could be computed (E7: with 5 digits the future rule would give `22`; today it is `None`).

### Replacement (decided, applied in Phase 2)

From Phase 2, replacing a physical meter creates a **new Meter record**, as recorded in [ADR-006](adr/ADR-006-meter-replacement-new-record.md):

- the old meter gets a final reading and becomes inactive;
- the new meter gets an approved `installed` event and a first reading.

Under one meter ID, the old meter's final reading and the new meter's first reading cannot share an instant without a timestamp conflict, so one ID always loses an interval. Two records keep both chains continuous.

## Undocumented decreases

**Decided (closes open question 8):** a decrease with no approved event stays `unexplained_decrease`, with no kWh, until a person records and approves a `reset` or `replaced` event. The chain is then recomputed and the pair becomes a `meter_boundary`.

The system never infers the cause. There is no heuristic for "the new value is near zero, so it must be a reset". A wrong guess would either invent consumption or hide a real data entry error. Letting the system draft (never approve) such an event is possible later work.

Model or tool output can never record or approve a meter event without the confirmation and audit rules in the [security and operations document](08-SECURITY-OPERATIONS.md).

## Time normalization and coverage

From P1-04 (`readings/normalization.py`, [spec 0005](specs/0005-time-normalized-consumption-coverage/index.md)):

- **Rate:** `normalize_intervals` gives each valid interval `kwh_per_day` from real elapsed time. One day is 86,400 UTC seconds; a 36 hour interval is 1.5 days (E3). The rate is computed exactly and rounded once, half even, to 6 places. Invalid intervals get `None`.
- **Window:** `summarize_consumption` measures a half open UTC window `[window_start, window_end)`. Only valid intervals **fully inside** the window count toward `measured_kwh`.
- **No proration:** a valid interval that crosses a window bound contributes no kWh. Its in window part becomes a `partial_interval` gap (E11).
- **Gaps:** every uncovered span is a typed gap: `before_first_reading`, `after_last_reading`, `no_intervals`, `partial_interval`, or `invalid_interval` (which carries the interval reason and event IDs). Measured intervals and gaps tile the window exactly.
- **Coverage:** `coverage_ratio` is covered time over window time, rounded once, half even, to 4 places. The average rate is measured kWh over covered time, or `None` with no coverage.

## Operational trade offs

- **Strictness versus lost coverage.** Every reset, replacement, flag, or unexplained drop loses at least one interval of kWh. A resident who forgets to record an event sees a gap until someone approves one. We accept lower coverage so that every number shown is measured.
- **Reading cadence versus partial intervals.** A window only counts intervals fully inside it. Weekly readings against a monthly window lose up to two partial weeks at the edges. Reading closer to the window bounds (for example on the bill period dates) raises coverage.
- **Capturing resets and replacements.** The practice that loses the least: take a final reading just before the work, record the event, then take a first reading at the event instant. The reading at the event instant starts the new segment, so only the one boundary pair is lost. With a replacement in Phase 2, the final reading goes on the old Meter and the first reading on the new one.
- **Late or backfilled readings.** Intervals and summaries are derived, never stored. Adding a missing reading, voiding a bad one, or approving an event changes the result the next time the chain is computed. There is no cached kWh to correct.
- **Manual versus imported readings.** Both sources follow the same rules; `source` is provenance only. Imported data still has to be one cumulative register value per instant. Incremental exports are not readings (see Incremental readings).
- **Implausible spikes.** A large jump is valid in the domain (E12: `117441.0` kWh in one day from a typo with an extra digit). This is a known risk. Today a person can flag or void the reading. The planned detector is anomaly scoring in Phase 5 (P5-04); no ingestion threshold is set in Phase 2 because there is no evidence yet for a value.
- **Measured kWh can be lower than a bill total.** A bill covers its whole period. A window summary only counts measured intervals and reports the rest as gaps. The difference is shown as missing coverage, never filled in.
- **Ownership.** These functions are pure and read no stored data. Ownership checks on every meter, reading, and event arrive with persistence in Phase 2, and no model or tool execution may bypass them.

## Worked examples

All instants are UTC on November 2026 dates (`01 12:00` means 2026-11-01 12:00 UTC). `R(value @ time)` is a valid manual reading unless marked. Each example has exactly one test, `test_e<N>_<slug>`, in `backend/tests/test_meter_semantics_examples.py`. If you change a number here, change the test too.

| ID | Case | Input | Expected |
|---|---|---|---|
| E1 | normal pair | `R(13007.10 @ 01 12:00)`, `R(13019.30 @ 02 12:00)` | valid, `12.20` kWh, `12.200000` kWh/day |
| E2 | no use | `R(13019.30 @ 02 12:00)`, `R(13019.30 @ 03 12:00)` | valid, `0` kWh |
| E3 | non 24 hour interval | `R(100.0 @ 01 00:00)`, `R(106.0 @ 02 12:00)` | valid, `6.0` kWh, `4.000000` kWh/day |
| E4 | unexplained decrease | `R(13019.30 @ 02 12:00)`, `R(13010.00 @ 03 12:00)`, no events | invalid `unexplained_decrease`, kWh `None` |
| E5 | approved reset at reading instant | `R(13019.30 @ 02 12:00)`, `R(0.40 @ 03 12:00)`, `R(5.40 @ 04 12:00)`; approved `reset` at `03 12:00` | pair 1 invalid `meter_boundary` with the event ID; pair 2 valid `5.00` kWh |
| E6 | unapproved reset | as E5, event not approved | pair 1 invalid `unapproved_event`; pair 2 valid `5.00` kWh |
| E7 | approved rollover | `R(99990 @ 01 12:00)`, `R(12 @ 02 12:00)`; approved `rollover` at `02 12:00` | invalid `unsupported_event`, kWh `None` (the future rule would give `22` with 5 digits; not computed) |
| E8 | approved calibration | `R(500.0 @ 01 12:00)`, `R(510.0 @ 02 12:00)`; approved `calibration` at `01 18:00` | invalid `unsupported_event`, kWh `None` |
| E9 | flagged middle reading | `R(100.0 @ 01)`, flagged `R(150.0 @ 02)`, `R(120.0 @ 03)` (all 12:00) | two invalid `flagged_reading` intervals, no kWh |
| E10 | voided middle reading | `R(100.0 @ 01)`, voided `R(150.0 @ 02)`, `R(120.0 @ 03)` (all 12:00) | one valid interval `01` to `03`, `20.0` kWh |
| E11 | window cuts an interval | `R(100.0 @ 01 00:00)`, `R(110.0 @ 02 00:00)`, `R(130.0 @ 03 00:00)`; window `[01 00:00, 02 12:00)` | `measured_kwh` `10.0`; one `partial_interval` gap `[02 00:00, 02 12:00)`; `coverage_ratio` `0.6667` |
| E12 | implausible spike | `R(13049.0 @ 01 12:00)`, `R(130490.0 @ 02 12:00)` | valid, `117441.0` kWh (documented known risk) |
| E13 | two date only readings, same local date | two readings at `03 16:00` (12:00 in `America/Santo_Domingo`), `original_local_date` `2026-11-03`, values `200.0` and `201.0` | `order_readings` reports one conflict group with both; `compute_intervals` raises `ValueError` |

## Out of scope and future work

- **Incremental data type** for bill periods and interval exports, and how a bill period is compared against a window summary (Phase 4).
- **Register digit count** on the Meter, which enables rollover kWh (Phase 2 spec).
- **Replacement link** from a new Meter to the one it replaces, with constraints and migrations (Phase 2 spec, per ADR-006).
- **Date only conversion** at the API boundary, with tests for the 16:00 UTC result and the same day conflict (P2-04).
- **Drafted events:** whether the system may draft (never approve) a reset or replacement event when it sees a decrease (later).
- **Spike detection** by anomaly scoring (Phase 5, P5-04).
- Proration, interpolation, or any estimated kWh: not planned. Gaps stay gaps.
