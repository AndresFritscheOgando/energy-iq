# 0007. Meter semantics, discontinuity rules, and operational trade offs

**Date**: 2026-11-03
**Status**: Accepted

## Summary

This spec covers P1-06, the last Phase 1 ticket. It produces one reference document, `docs/12-METER-SEMANTICS.md`, that explains how EnergyIQ reads a meter: readings are cumulative (the running total on the register), consumption only exists between two readings with no break in between, and every break (reset, replacement, rollover, a flagged reading, an unexplained drop) is reported, never guessed around. It also closes two open Phase 1 questions: date only readings get a fixed noon local time, and an unexplained drop stays invalid until a person records and approves an event. Each worked example in the document gets a matching test, so the document cannot quietly drift from the code. No application behavior changes.

## Requirements

**User stories**:
- As the engineer starting Phase 2, I want one place that states what a reading means and when kWh is known or unknown, so that the API, database constraints, and UI do not reinvent the rules.
- As a reviewer or portfolio reader, I want the trade offs (what strictness costs, why nothing is estimated) written down with real numbers, so that I can judge the design without reading four specs.
- As the engineer, I want every worked example in the document to be checked by a test, so that a later code change that breaks a documented rule fails the suite.

**Acceptance criteria**:
- **AC-1 (document and links)**: `docs/12-METER-SEMANTICS.md` exists with these sections, in this order: Purpose; Cumulative readings; Incremental readings; Time and ordering; Discontinuity rules; Meter events; Undocumented decreases; Time normalization and coverage; Operational trade offs; Worked examples; Out of scope and future work. It is linked from `README.md` (domain table or docs list), `docs/04-DATA-MODEL-API.md` (Meter entity and invariant 3), `docs/11-DECISIONS-OPEN-QUESTIONS.md`, and the roadmap P1-06 entry. Every local link added or edited in P1-06 resolves, including heading anchors. Links that already existed before P1-06 in the changed documents are out of scope; any that do not resolve (for example links to the removed specs 0001 to 0004 and task files) are recorded as a known gap in `docs/PROGRESS.md`, not fixed here.
- **AC-2 (cumulative vs incremental)**: The document states that a reading is a cumulative register value in kWh (a `Decimal`, at most 6 fractional places, from 0 to `999999999999.999999`), that consumption is the exact difference of two consecutive non voided readings within one unbroken segment, and that equal values give a valid 0 kWh. It defines incremental data (kWh per period, such as bill period totals or smart meter interval exports), and states the rule: incremental data is never turned into synthetic cumulative readings. Phase 4 compares bill period kWh against a measured window summary and never merges the two. A separate incremental type is future work, not designed here.
- **AC-3 (discontinuity rules match the code exactly)**: The document has one table row per `IntervalReason` (`flagged_reading`, `unapproved_event`, `meter_boundary`, `unsupported_event`, `unexplained_decrease`) plus the valid case, each naming the condition, the interval status, and that kWh is `None` for every invalid row. It states the precedence exactly as `compute_intervals` applies it: any event in the pair first (`unapproved_event` if any event is unapproved, else `unsupported_event` if any is `rollover` or `calibration`, else `meter_boundary`), then a flagged endpoint, then a decrease, else valid. It states the event timing rule: an event belongs to the pair where `previous.recorded_at < effective_at <= current.recorded_at`, so a reading taken at the event instant is the first reading of the new segment. It states that voided readings are skipped (the pair bridges over them) while flagged readings are barriers (both neighbouring pairs are invalid), and that any timestamp conflict stops interval calculation for the whole chain.
- **AC-4 (meter events, now and later)**: For each `MeterEventType` the document states today's handling and the planned direction. `installed`, `reset`, `replaced`: approved means `meter_boundary`. `calibration`: always `unsupported_event` (an accuracy adjustment, never a source of kWh). `rollover`: `unsupported_event` until the Meter stores its register digit count; the future rule is `kWh = (10^digits − previous) + current`, valid only for an approved rollover event and a result below `10^digits`. Replacement: from Phase 2 a replacement creates a new Meter record (old meter gets a final reading and becomes inactive; new meter gets an approved `installed` event and a first reading), recorded in `docs/adr/ADR-006-meter-replacement-new-record.md`. The in chain `replaced` event stays supported for data recorded under one meter ID.
- **AC-5 (open questions closed)**: The document records two decisions, and `docs/11-DECISIONS-OPEN-QUESTIONS.md` moves open items 4 and 8 to Recorded decisions with links (the remaining items keep their numbers or are renumbered consistently). Decision for item 4: the domain keeps requiring an exact UTC instant; a date only manual reading is converted at the API boundary in P2-04 to 12:00 local time in `America/Santo_Domingo` on that date (always 16:00 UTC, since the zone has no daylight saving time), with `original_local_date` kept as provenance; two date only readings on the same local date, or one at exactly that instant, form a timestamp conflict handled by the P1-02 conflict flow. Decision for item 8: a decrease without an approved event stays `unexplained_decrease` with no kWh until a person records and approves a reset or replacement event; the system never infers the cause.
- **AC-6 (normalization and trade offs)**: The document summarizes P1-04: kWh per day uses real elapsed time (one day is 86,400 UTC seconds) and is rounded once, half even, to 6 places; a window summary measures only valid intervals fully inside the half open window `[start, end)`; a valid interval that crosses a window bound contributes no kWh and becomes a `partial_interval` gap (no proration). The Operational trade offs section covers at least: strictness versus lost coverage; reading cadence versus partial intervals; the capture practice for resets and replacements (a final reading just before, the event, a first reading at the event instant); late or backfilled readings (intervals are derived and recomputed, never stored); manual versus imported readings; implausible spikes (valid in the domain, a known risk that a person can flag or void, with Phase 5 anomaly scoring as the planned detector); and why measured kWh can be lower than a bill total (gaps are reported, not filled).
- **AC-7 (worked examples are tested)**: The Worked examples section lists examples `E1` to `E13` from the table in Feature design, each with its input readings, events, and expected result. `backend/tests/test_meter_semantics_examples.py` has exactly one test per example, named `test_e<N>_<slug>`, using the same numbers, importing only from `energyiq.readings`. The section names the test file. No application source changes. If an example shows the code and the document disagree, the build stops for the engineer's decision; specs 0004 and 0005 stay the contract until then.
- **AC-8 (checks, progress, and phase gate)**: The full suite, `ruff check .`, `ruff format --check .`, and `pyright` pass. `docs/PROGRESS.md` and the roadmap P1-06 entry record the outcome and the checks actually run. The Phase 1 exit gate is recorded as passed only if P1-05 has a passing `/check verify` record by then; otherwise it is recorded as pending P1-05 verification.

## Decision

**Chosen option**: Option 1: a standalone domain reference with tested worked examples, plus targeted decisions

Write `docs/12-METER-SEMANTICS.md` as the single reference for reading semantics, back each worked example with one test against the public API, close open questions 4 and 8, and record the replacement direction as ADR-006.

**Decisions made in this spec** (each a call the build would otherwise invent):
- **Cumulative readings are canonical. Incremental data is a separate future type**, never converted into synthetic cumulative readings. Runner up: a running sum conversion, which invents an anchor value and hides where the data came from.
- **Undocumented decreases stay strict.** No inference, no heuristic for a near zero value. A human records and approves the event. Runner up: system drafted events for approval, noted as possible later work.
- **Rollover stays unsupported** until the Meter stores its register digit count. The future formula is recorded so Phase 2 can add the field on purpose. Runner up: implementing it now, which would add behavior to a documentation ticket.
- **Replacement creates a new Meter record from Phase 2** (ADR-006). Under one meter ID the old final reading and the new first reading cannot share an instant without a conflict, so a separate record is the only way to keep both chains continuous. Runner up: keeping one ID and accepting the lost interval.
- **Date only readings become 12:00 local, 16:00 UTC**, applied at the API boundary in P2-04, never inside the domain. Noon is the time least likely to sort out of order against a same day timestamped reading. Runner up: 00:00 local, which sorts before every same day reading.
- **Implausible spikes stay valid in the domain.** Detecting them belongs to Phase 5 anomaly scoring; a person can flag or void the reading today. Runner up: a Phase 2 ingestion threshold, which has no evidence for a value yet.
- **Example test module is `backend/tests/test_meter_semantics_examples.py`**, one test per example, IDs shared with the document. Runner up: linking existing tests from the document, which lets the document's numbers go stale silently.
- **ADR-006 covers replacement only.** The other decisions are domain rules and live in the document and in `11-DECISIONS`. One ADR per significant architectural change keeps ADRs short. Runner up: one broad "meter semantics" ADR, which would duplicate the document.
- **The AC-1 link check covers only links added or edited in P1-06.** Older broken links (to specs and task files removed in an earlier cleanup) are recorded as a known gap, not repaired, so this ticket stays a documentation change with a clear edge. Runner up: fixing every broken link in the changed files, which pulls an unrelated cleanup into P1-06.
- **No `docs/scope/` row exists**, so the build tasks below are the source of truth, as in specs 0005 and 0006.

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

**Data model sketch**:
No schema or record changes in this ticket. `Reading`, `MeterEvent`, `ConsumptionInterval`, `NormalizedInterval`, `ConsumptionGap`, and `ConsumptionWindowSummary` stay as built in specs 0002 to 0005. The document records two future fields as direction, not design: a Meter register digit count (needed for rollover) and a link from a replacement meter to the meter it replaces (ADR-006). Phase 2 designs both, with names, types, and constraints, in its own spec.

**State transitions**:
Segment view of one meter chain (derived, never stored):
`open segment` → (approved `reset` / `replaced` / `installed` event in a pair) → `boundary pair, kWh unknown` → (next reading pair with no event) → `new open segment`.
`open segment` → (flagged reading) → `two invalid pairs` → (next unflagged pair) → `open segment`.
`open segment` → (decrease with no event) → `invalid pair` → (person records and approves an event, chain recomputed) → `boundary pair`.
Unapproved, `rollover`, and `calibration` events keep the pair invalid until approved (and, for rollover and calibration, until future support exists).

**API surface**:
No HTTP surface in this ticket. The document describes the existing public library API in `energyiq.readings`:

| Function | Kind | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `order_readings` | pure function | iterable of `Reading` for one meter | `ReadingOrderResult(ordered, conflicts)` | none (no data access; Phase 2 adds ownership) | `TypeError` or `ValueError` with index for a bad item or mixed meters |
| `compute_intervals` | pure function | conflict free `ReadingOrderResult`, iterable of `MeterEvent` | tuple of `ConsumptionInterval` | none | `ValueError` on conflicts, bad order, or an event for another meter |
| `normalize_intervals` | pure function | complete touching interval chain | tuple of `NormalizedInterval` | none | `ValueError` on a broken chain |
| `summarize_consumption` | pure function | interval chain, `meter_id`, `window_start`, `window_end` | `ConsumptionWindowSummary` | none | `ValueError` if `window_end <= window_start` |

**Value sourcing** (every rule the document states names its source of truth):
| Document section | Value or rule stated | Source |
|---|---|---|
| Cumulative readings | kWh scale, range, nonnegative, finite | `readings/models.py` `_validate_kwh`; spec 0002 |
| Cumulative readings | consumption is the exact difference | `consumption.calculate_consumption`; spec 0001 |
| Time and ordering | stable order, conflict groups | `readings/ordering.py`; spec 0003 |
| Time and ordering | date only rule (12:00 local, 16:00 UTC, provenance, conflict) | decided in this spec (AC-5); applied in P2-04 |
| Discontinuity rules | reasons, precedence, event window, voided and flagged handling | `readings/intervals.py` `compute_intervals`, `_event_reason`; spec 0004 |
| Meter events | rollover formula and digit count prerequisite | decided in this spec (AC-4) |
| Meter events | replacement creates a new Meter | ADR-006, written in this ticket |
| Undocumented decreases | strict policy | decided in this spec (AC-5) |
| Time normalization and coverage | rate rounding, half open window, gap reasons, no proration | `readings/normalization.py`; spec 0005 |
| Operational trade offs | spike risk owner | Phase 5 tickets P5-04 in the roadmap |
| Worked examples | every number and expected result | `backend/tests/test_meter_semantics_examples.py` (AC-7) |

**Worked examples** (the document and the test module both use exactly these; all instants UTC on 2026-11 dates; `R(value @ time)` is a valid manual reading unless marked):

| ID | Case | Input | Expected |
|---|---|---|---|
| E1 | normal pair | `R(13007.10 @ 01 12:00)`, `R(13019.30 @ 02 12:00)` | valid, `12.20` kWh, `12.200000` kWh/day |
| E2 | no use | `R(13019.30 @ 02 12:00)`, `R(13019.30 @ 03 12:00)` | valid, `0` kWh (value equal to `Decimal("0")`) |
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

**Key invariants**:
- The document never states a rule the code does not enforce, except rules marked "decided, applied in Phase N" (date only conversion, rollover formula, replacement as a new Meter).
- Every example ID in the document has exactly one test, and every `test_e<N>_` test has exactly one example.
- No kWh value is ever estimated, prorated, or inferred in any rule or example.

**Security model**:
No data access and no new surface. Examples use synthetic values and random UUIDs only, never real bill or account data. The document states that ownership checks arrive with persistence in Phase 2 and that model or tool output can never record or approve a meter event without the confirmation and audit rules in `docs/08-SECURITY-OPERATIONS.md`.

**Configuration required**: none.

**Critical test scenarios** (each maps to an acceptance criterion in ## Requirements):
- Happy path: E1 to E3 give exact kWh and rates through the public API, verifies **AC-2**, **AC-6**, **AC-7**
- Failure case: E4 to E10 each return the documented reason and no kWh, in the documented precedence, verifies **AC-3**, **AC-4**, **AC-7**
- Window and conflict: E11 drops the cut interval into a `partial_interval` gap, and E13 stops on a same day date only conflict, verifies **AC-5**, **AC-6**, **AC-7**
- Auth/permission: not applicable (pure functions, no data access); the document states where ownership enforcement lands, verifies **AC-1**

## Build plan

Build approach: none is recorded in `AGENTS.md`, so this follows the end to end default used in specs 0005 and 0006. The thin thread here is "one example, tested and documented", then it thickens.

1. [x] Create `backend/tests/test_meter_semantics_examples.py` with E1 to E13 from the table, one test each, importing only from `energyiq.readings`. Run it. If any expected result differs from the code, stop and report the mismatch for the engineer's decision. Satisfies **AC-7**.
2. [x] Write `docs/12-METER-SEMANTICS.md` with the AC-1 sections: cumulative and incremental semantics, time and ordering (including the date only rule), the discontinuity table and precedence, meter events now and later, the undocumented decrease policy, normalization and coverage, the operational trade offs, the E1 to E13 table pointing to the test file, and out of scope items. Satisfies **AC-1** to **AC-6**.
3. [x] Write `docs/adr/ADR-006-meter-replacement-new-record.md` in the ADR-005 format (Status Accepted, Date, Context, Decision, Consequences, Revisit trigger). Satisfies **AC-4**.
4. [x] Update `docs/11-DECISIONS-OPEN-QUESTIONS.md` (add ADR-006 and the two closed decisions to Recorded decisions, remove items 4 and 8 from the open list), `docs/04-DATA-MODEL-API.md` (Meter entity note on replacement, invariant 3 link), `README.md` (link to the new document), and the roadmap P1-06 entry. Run a local link check on every changed Markdown file; links added or edited in P1-06 must resolve, and broken links that predate P1-06 go to the PROGRESS known gaps. Satisfies **AC-1**, **AC-5**.
5. [x] Run the full suite, `ruff check .`, `ruff format --check .`, and `pyright`. Update `docs/PROGRESS.md` with the outcome and the checks run. Check P1-05: if spec 0006 has a passing `/check verify` record, mark the Phase 1 exit gate passed in the roadmap and PROGRESS; otherwise record it as pending P1-05 verification. Satisfies **AC-8**.

## Consequences

**Positive**:
- Phase 2 starts from one written contract for reading semantics, so database constraints and API errors follow rules that are already decided.
- Two open Phase 1 questions are closed with concrete rules, so P2-04 does not stall on them.
- The examples test pins the documented behavior; a future change to interval rules must update the document too.

**Negative / tradeoffs**:
- Strictness costs coverage: every reset, replacement, flag, or unexplained drop loses at least one interval of kWh, and a resident who forgets to record an event sees gaps until someone approves one.
- The noon rule can misorder a date only reading against a same day timestamped reading taken in the afternoon; the order is deterministic, but not always the real one.
- Rollover data recorded before Phase 2 adds the digit count stays without kWh, even though it could be computed.
- The document is another artifact to keep in sync; the examples test covers the numbers, but prose rules can still drift.

**Neutral**:
- The new test module adds 13 small tests and no dependency.
- Spec 0007 sits under the `/docs` ignore rule like specs 0001 to 0006 and needs force staging when committed.

## Follow-up

- [ ] Phase 2 spec: design the Meter register digit count field and the replacement link (ADR-006), with constraints and migrations.
- [ ] P2-04: implement the date only conversion at the API boundary and test the 16:00 UTC result and the same day conflict.
- [ ] Later: decide whether the system should draft (never approve) reset or replacement events when it sees a decrease.
- [ ] Phase 4: design the incremental bill period type and how a bill period is compared against a window summary.
- [ ] Run `/check verify` for P1-05 before P1-06's gate step, so the Phase 1 gate can be recorded as passed.
