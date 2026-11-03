# Rationale: 0005. Time normalized consumption rates and window coverage gaps

Decision record for [spec 0005](index.md).

## Context

P1-03 turns ordered readings into a chain of intervals. Each interval is either valid, with an exact kWh value, or invalid, with a reason and no kWh. That answers "how much energy between these two readings", but not the question residents actually ask: "how much do I use per day, and over this month?" Readings arrive at uneven times. One pair may be 20 hours apart and the next 9 days apart, so raw interval kWh values cannot be compared, charted, or summed into a period without accounting for time. Data model invariant 3 says rates must use the actual elapsed time, never assume a pair is 24 hours apart. PRD FR-04 requires date normalized usage.

Missing data is the second force. Invariant 9 and the testing rules forbid making up readings or interpolating missing data into factual consumption. User stories ask for intervals with duration and coverage, and for usage graphs with gap indicators so missing data is never mistaken for zero. A window can lose data in several ways. It can begin before the first reading or end after the last one. It can contain an interval P1-03 marked invalid (meter event, flagged reading, unexplained decrease). Or it can cut through the middle of a valid interval, whose kWh cannot be split exactly at the window edge. Callers (the Phase 2 `GET /meters/{id}/consumption?from=&to=` endpoint, the Phase 3 chart, and later forecasting and reconciliation) need each of these named and located precisely.

Arithmetic is the third force. Dividing kWh by elapsed time is almost never exact in decimal, so rounding is unavoidable and must be declared and tested. The existing `elapsed_hours` helper returns a binary float, which the repository rules forbid for authoritative totals. Timestamps are UTC instants. The property timezone (`America/Santo_Domingo`) is a display concern and has no daylight saving changes.

If this stays undecided, every caller would do its own normalization, round differently, and decide differently what counts as missing. That is exactly how a chart ends up showing a gap as zero usage, or a bill comparison ends up quietly using estimated kWh.

## Options considered

### Option 1: Per interval rates plus an exact window summary with typed gaps

Give each interval its own kWh per day rate from its real elapsed time. For a requested window, add up only the valid intervals that sit fully inside it, and list every other piece of the window as a typed gap. A valid interval cut by a window edge becomes a `partial_interval` gap.

**Pros**:
- Every number shown is measured fact, which satisfies invariant 9 and the no interpolation rule with no special labels.
- The gap list is a complete, traceable explanation of missing coverage, ready for a chart's gap indicators and for reconciliation.
- Pure and deterministic, and it builds directly on the P1-03 output.

**Cons**:
- A window whose edges fall between readings loses the edge intervals entirely, so coverage can look low even when readings are frequent. A month window over readings taken every 10 days may report only around 60 percent coverage.
- Callers who want calendar day bars must build them later, as estimates, with their own spec.

### Option 2: Spread interval kWh across calendar days in the property timezone

Split each valid interval's kWh across the local calendar days it spans, in proportion to time, and return daily values plus daily coverage.

**Pros**:
- Exactly the shape a daily usage chart wants.
- Windows can always be aligned to whole days with no partial interval loss.

**Cons**:
- Every daily value from an interval longer than a day is an estimate that assumes flat usage, which conflicts with invariant 9 unless every value carries an estimate label.
- It pulls the property timezone and calendar day rules into the domain layer before any property model exists.
- Rounding many daily shares can make their sum differ from the interval total, so it needs a remainder rule.

### Option 3: Expand the window outward to whole intervals

Include every valid interval that overlaps the requested window in full, and report the actual measured bounds, which may be wider than the request.

**Pros**:
- No partial interval loss, and totals stay exact.
- Coverage looks better when readings are sparse.

**Cons**:
- Two adjacent windows can both count the same interval, so summing monthly summaries double counts energy.
- The reported bounds differ from what was asked for, which callers can easily misread.

## Rationale

The deciding force is invariant 9 together with the user story requirement that missing data never be mistaken for zero. Option 2 is the friendliest chart shape, but every daily value from a multi day interval is an assumption about how usage was spread out. Building that into the authoritative domain layer in Phase 1 would make estimated numbers the default, which conflicts with ADR-003's line between deterministic facts and everything else. Option 3 keeps totals exact but breaks additivity: adjacent windows double count shared intervals, which would quietly corrupt later monthly sums and bill reconciliation (invariant 4). Option 1 is the only choice where every number is measured fact, windows add up without double counting, and lost coverage is explained rather than hidden.

The cost of Option 1 is that coverage looks lower when windows do not line up with reading times. That is the honest answer: the system really does not know how much of an edge interval's energy fell inside the window. A later presentation feature can still offer clearly labelled estimates (Option 2) on top of this contract, but the reverse would not be safe. Reporting durations rather than a fixed sparseness threshold keeps P1-04 free of a number nobody can justify yet. The chart in Phase 3 can choose its own rule.

Exact rational arithmetic with one final rounding fits the repository's money and kWh discipline. The repo already rejects binary floats and silent rounding. `Fraction` is standard library, needs no context setup, and makes the rounding rule easy to test exactly. Requiring the full touching chain from `compute_intervals` (rejecting holes) catches caller bugs, such as filtering out invalid intervals before summarizing, which would otherwise turn invalid data into a fake `before_first_reading` gap or silently skip it.
