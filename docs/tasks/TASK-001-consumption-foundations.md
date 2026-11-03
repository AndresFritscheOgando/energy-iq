# Task 001 — Deterministic Consumption Foundations

**Phase:** 0. **Related tickets:** P0-02, P0-03, P0-04. **Story:** US-001.

## Objective
Implement and verify deterministic cumulative-reading differences and elapsed time. This task specification replaces Lesson 001; the architect implements the code and tests directly.

## Implemented contracts
- `calculate_consumption(previous_reading: Decimal, current_reading: Decimal) -> Decimal` returns the cumulative kWh difference.
- Reject negative or decreasing readings with `ValueError`; equal readings return zero. A meter reset or replacement must not be interpreted as ordinary consumption.
- P0-06 adds `TypeError` for non Decimal inputs, including integers, floats, and bools, and `ValueError` for NaN, signaling NaN, and infinities before comparisons. Signed zero is valid.
- Subtraction uses an isolated Decimal context with precision 28, `ROUND_HALF_EVEN`, `Emin=-999999`, and `Emax=999999`. Results are exact or raise a Decimal arithmetic exception. Caller context settings and flags are preserved. Exact subnormal results are allowed; removing representational trailing zeros without numeric loss is allowed. This is a computation policy, not a storage scale.
- `elapsed_hours(previous_at: datetime, current_at: datetime) -> float` accepts timezone-aware, zero-offset timestamps and requires `current_at > previous_at`.
- Elapsed hours include complete days and fractional hours. Reject naive, nonzero-offset, equal, and reversed timestamp pairs with `ValueError`.
- Unsupported elapsed time argument types raise an argument specific `TypeError` before timezone access. Elapsed hours remain a float and can have floating point approximation.

## Acceptance cases
| Previous kWh | Current kWh | Expected |
|---|---|---|
| 13007 | 13049 | 42 kWh |
| 12964 | 12979 | 15 kWh |
| 15000 | 15000 | 0 kWh |
| 15000 | 14900 | ValueError |
| -5 | 100 | ValueError |
| 0 | 0 | 0 kWh |

Use string-constructed Decimal fixtures for exact fractional cases and verify the result type. Time cases cover 12 hours, 36 hours, half an hour, invalid timezone information, and invalid ordering.

## P0-04 observation-ordering contract
- `Observation` is a `(datetime, Decimal)` timestamp/cumulative-kWh pair for one meter. Full reading and meter-event models belong to Phase 1.
- `sort_observations(observations: Iterable[Observation]) -> list[Observation]` returns a new chronological list, accepts a single-pass iterable, and does not mutate the input collection.
- Every timestamp must be timezone-aware with a zero UTC offset, including singleton inputs. Reject invalid timestamps with an indexed `ValueError` before comparing observations.
- Unsupported timestamp types and pairs that cannot unpack into exactly two values raise indexed `TypeError`. Existing list pairs remain usable without coercion; the typed public contract remains a tuple. Failures from the outer iterable and custom timezone code propagate.
- Preserve timestamp/value pairing and the relative order of equal timestamps. Keep exact duplicates; formal same-meter duplicate rejection belongs to P1-02.
- This helper only orders observations: it does not validate kWh values, group meters, resolve duplicates, infer intervals, or fabricate readings. Callers supply observations for one meter; later domain validation enforces reading and continuity rules.
- Acceptance cases cover empty, singleton, already sorted, reversed, out-of-order, equal-timestamp, exact-duplicate, generator, named zero-offset, and invalid-timezone inputs. Input preservation is checked on success and validation failure.

## Definition of done
Relevant behavior is implemented, acceptance and edge-case tests pass, lint and formatting pass, and progress records actual verification. No conceptual assessment or independent user implementation is required.

## Verification and status
P0-04 completed on 2026-11-02. The full suite passed 42 cases: nine consumption, 12 elapsed-time, and 21 observation-sorting cases. Ruff lint and formatting passed for all five Python files. Actual commands/results are recorded in [progress](../PROGRESS.md).

P0-06 hardening completed on 2026-11-02 against [spec 0001](../specs/0001-phase-zero-domain-hardening.md). The final suite passed 166 cases, including exact arithmetic and context isolation, invalid runtime types, malformed observation pairs, and actual CLI subprocesses. Ruff lint and formatting passed. The Phase 0 review covered all five source files and all three test files.

## Follow-up scope
P0-05 delivered the [local CLI](TASK-002-consumption-cli.md), and P0-06 hardened direct domain calls. Phase 1 adds typed reading and meter event models, duplicate detection, discontinuity handling, and interval coverage.
