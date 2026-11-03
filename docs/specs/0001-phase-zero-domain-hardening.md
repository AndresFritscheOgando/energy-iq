# 0001. Phase zero domain hardening

**Date**: 2026-11-02
**Status**: Accepted

## Summary

You can finish Phase 0 by strengthening the existing domain functions. Reject invalid values at the function boundary and make Decimal subtraction return an exact result or a clear arithmetic error. Preserve the working CLI and observation contracts, then verify the full phase before marking it complete.

## Context

This is an ENHANCEMENT for roadmap ticket `P0-06`, supporting `US-001`. Python 3.13, Decimal, pytest, and Ruff are already in use. Eight Python files implement and test the domain helpers and local CLI. No new package, service, schema, or UI is needed.

Direct calls currently accept integers, can return infinity, and raise incidental exceptions for unsupported timestamp types. Subtraction inherits the caller's Decimal context (the settings controlling arithmetic). At precision 3, consumption from `0` to `1.234` silently becomes `1.23`.

The engineering contract delegates routine choices to the implementation engineer. Requirements, interfaces, UTC rules, synthetic fixtures, and phase boundaries are inferred from the existing task contracts. The recommendations below settle internal validation and arithmetic policy. No unresolved product input is needed. There is no scope file or prior numbered spec. This spec supplements Task 001 and Task 002, without replacing their completed contracts.

No delivery approach is recorded. Use Tracer Bullet slices (complete a small behavior through domain, CLI, and tests before extending it). This spec remains Proposed until implementation is verified. No cross model review or user ratification is claimed.

## Requirements

As a resident, you want a trustworthy consumption result or a clear error so an invalid reading cannot look like actual usage.

1. **AC-1**: `calculate_consumption` requires two Decimal instances. An integer, float, bool, string, `None`, or unrelated object in either position raises `TypeError`, identifying the argument. No implicit numeric conversion occurs.
2. **AC-2**: Either reading being NaN, signaling NaN, or either infinity raises `ValueError` before comparison or arithmetic. Finite negative or decreasing readings retain their existing `ValueError` behavior. Equal readings and signed zero remain valid.
3. **AC-3**: Successful consumption is a finite, numerically exact Decimal difference under the policy below. An unrepresentable result raises a `DecimalException` subtype. Ambient precision, rounding, exponent limits, traps, and flags do not change the outcome. The caller's context is preserved on success and failure.
4. **AC-4**: Both elapsed time arguments and every sorting timestamp require datetime instances. Unsupported types raise an argument specific or indexed `TypeError`. Existing naive, nonzero offset, equal, and reversed time validation stays intact. Named zero offset zones remain valid.
5. **AC-5**: Sorting still returns a new stable chronological list, preserves duplicates and timestamp/value pairing, accepts an iterable consumed once, and leaves the input collection unchanged. Malformed observation pairs fail with indexed `TypeError`. Sorting continues to leave kWh validation to later reading models.
6. **AC-6**: The actual module CLI preserves prompts, normal Decimal formatting, exit statuses, import safety, EOF, and cancellation. Unsupported arithmetic produces the existing stderr message with status 2 and no consumption result or traceback.
7. **AC-7**: A final review covers all Phase 0 source and tests. The full behavioral suite, Ruff lint, and Ruff formatting checks pass. README, task contracts, and progress accurately record actual results and remaining limits before Phase 0 is marked complete.

## Options considered

### Option 1: Harden the existing functions

Add runtime guards and an isolated Decimal policy to the existing modules. This preserves the public interfaces and makes every existing caller safer. The cost is an explicit supported arithmetic range and additional validation tests. This is the recommended option.

### Option 2: Add a parallel validated domain layer

New reading objects could validate values while the old functions remain available during migration. This helps when many consumers need gradual adoption. Here it duplicates boundaries across a tiny local application and brings Phase 1 models forward.

### Option 3: Replace the foundation directly

Rewrite around full reading models and arbitrary precision subtraction. This offers one unified abstraction and a wider numeric range. It also expands the ticket, changes working interfaces, and needs a separate resource policy for extreme exponents.

## Decision

**Chosen option**: Option 1, harden the existing functions.

Recommend `TypeError` for unsupported runtime types, `ValueError` for invalid domain values, and Decimal arithmetic exceptions for unsupported exact results. These separate developer misuse from invalid readings and arithmetic limits. Normal CLI input remains string parsed Decimal input.

Recommend an explicit local Decimal context with precision 28, `ROUND_HALF_EVEN`, `Emin=-999999`, `Emax=999999`, `capitals=1`, and `clamp=0`. Enable traps for `InvalidOperation`, `DivisionByZero`, `Overflow`, `Underflow`, and `Inexact`; disable other traps. Clear local flags for each calculation. `Inexact` rejects loss of numeric value. `Rounded` alone is permitted because discarding trailing zeros can preserve the exact value. Exact subnormal results (very small values) are allowed. This is a computation limit, not a meter scale or tariff rule.

The runner up is a context whose precision grows with the operands. A fixed policy fits the existing arithmetic error contract and avoids allocating precision proportional to a hostile exponent gap. Future reading models may introduce physical ranges and decimal scale with their own specification.

## Rationale

The current boundaries are small and already exercised through real CLI subprocesses. Strengthening them directly closes the observed gaps without introducing a second model or migrating consumers. Keeping precision 28 and the default exponent range preserves ordinary behavior while replacing silent rounding with an explicit failure.

## Feature design

### Data and function surface

No persistent entities, relationships, keys, migrations, lifecycle states, credentials, or configuration are added.

| Surface | Required inputs | Output | Errors |
|---|---|---|---|
| `calculate_consumption` | previous and current finite nonnegative Decimal values in cumulative kWh | Exact Decimal difference | `TypeError`, `ValueError`, `DecimalException` subtype |
| `elapsed_hours` | previous and current UTC datetime values | Existing float duration in hours | `TypeError`, `ValueError` |
| `sort_observations` | Iterable of pairs containing datetime and Decimal | New chronological list of original pairs | Indexed `TypeError` for malformed pair or timestamp, indexed `ValueError` for timezone |
| `main` and `python -m energyiq` | Two prompted reading strings | Existing stdout, stderr, and process statuses | Handled input, domain, arithmetic, EOF, and cancellation cases |

### Validation and calculation rules

Validate both reading types before inspecting values. Validate both values with `is_finite()` before negative or ordering comparisons, including signaling NaN. Then check previous negative, current negative, and decreasing order, preserving the existing messages. Signed zero is nonnegative; no sign normalization is required.

Subtract only inside a fresh local copy of the explicit policy. Do not mutate the process context or reuse mutable flags across calls. Do not quantize kWh or convert through float. Preserve ordinary trailing fractional zeros such as `0.20`; extreme values may lose representational zeros when their numeric value stays exact. Bounds apply to the computed result, not to a future stored reading schema. Equal large readings can therefore return exact zero.

Validate datetime types before calling `utcoffset()`. Preserve the existing zero offset requirement and strict elapsed time ordering. A small private validator in `observations.py` may remove repeated checks; do not add a shared validation framework. Float elapsed hours retain their current approximation behavior, including for microseconds.

Materialize the outer observation iterable once. At each index, require an item that unpacks into exactly two values, then validate its timestamp before sorting. Report ordinary unpacking type or arity failures as indexed `TypeError`. Do not broadly catch failures raised by the outer iterable or custom timezone implementations. Preserve each original pair; do not coerce its kWh value or reject duplicates. Lists used as pairs can retain the existing unpacking behavior; the documented typed form remains `tuple[datetime, Decimal]`.

### Value sourcing

| Produced value | Source |
|---|---|
| Consumption in kWh | Current Decimal input minus previous Decimal input under the policy in Decision |
| Supported arithmetic outcome | Local context parameters and traps in Decision |
| Argument or observation index in errors | Function argument name or zero based position in the materialized iterable |
| Sorted observation order | Validated timestamp, using stable sorting on timestamp alone |
| Elapsed hours | Positive datetime difference, total seconds divided by 3600 |
| CLI result and exit status | Domain result or handled exception, using Task 002 conventions |
| Completion evidence | Commands actually executed and final review findings |

### Security and operational boundaries

These are pure local calculations without storage, accounts, authorization context, external model calls, logs, retries, or network operations. Use synthetic fixtures. Ownership enforcement begins with later data access; no ownership service belongs in these helpers. This ticket does not impose CLI text length limits or a resource bound on arbitrary iterables. Authentication, API schemas, tariffs, meter events, duplicate rejection, and installed packaging remain later scope.

### Critical test scenarios

| Cases | Criteria |
|---|---|
| Unsupported numeric types in either position, including bool | AC-1 |
| Quiet and signaling NaN, signed infinities, signed zero, negatives, decreasing and equal readings | AC-2 |
| Existing exact fractions and a result requiring more than 28 significant digits | AC-3 |
| Different caller precision, rounding, exponent limits and disabled traps; caller flags preserved on success and failure | AC-3 |
| Overflow at `0` to `1e1000000`, exact `1e-1000026`, rejected `1e-1000027`, and cancellation of equal large readings | AC-3 |
| Unsupported timestamp types in either time argument and singleton sorting input; all existing timezone cases | AC-4 |
| Empty and malformed pairs at several indices, stable equal timestamps, duplicates, generator, unchanged input after failure | AC-5 |
| Real CLI subprocess for exact success, precision rejection and overflow, with stderr and status assertions | AC-6 |
| Existing full suite plus new regression cases and final code review | AC-7 |

## Build plan

1. Complete a vertical validation slice through consumption, direct tests, and CLI regression checks. Add type and finite guards, preserving ordinary output and domain messages. Satisfies AC-1, AC-2, AC-6.
2. Complete the arithmetic slice through the explicit local context, direct context isolation tests, and actual CLI arithmetic failure cases. Satisfies AC-3, AC-6.
3. Complete the timestamp slice through elapsed time and sorting. Add type and pair shape errors, retaining the existing ordering contracts. Satisfies AC-4, AC-5.
4. Review every Phase 0 source file and relevant tests, resolve defects within this contract, run full checks, update the affected contracts and README, and record the phase gate honestly. Satisfies AC-1 through AC-7.

Suggested checks use the existing environment: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`, `.venv/Scripts/ruff.exe check backend`, and `.venv/Scripts/ruff.exe format --check backend`. Static typing is not a Phase 0 gate. No dependency installation is needed. No commit is requested.

## Consequences

You get predictable domain failures and protection against silent arithmetic rounding. Existing source imports and CLI invocation stay usable without a data migration.

Callers relying on implicit integer arithmetic will need to construct Decimal inputs explicitly. Results outside the supported exact arithmetic policy will fail, even when the caller supplies a larger context. Later persistence work still needs its own validated meter ranges and scale.

## Follow-up

1. Implement this spec for P0-06 before advancing to P1-01 reading and meter event models.
2. Record final Phase 0 evidence only after the implementation checks pass. The architect baseline is evidence for the existing code, not acceptance of the proposed hardening.

## Inspection evidence

On 2026-11-02, the existing suite passed 80 tests, Ruff lint passed, and Ruff reported eight files already formatted. Diagnostic calls accepted `(1, 2)` and returned integer `1`, returned infinity for Decimal inputs `0` and infinity, and returned `1.23` for `0` to `1.234` with caller precision 3. An unsupported timestamp raised `AttributeError`.

Small standard library probes confirmed the proposed context returns `0.20` for `13007.10` to `13007.30`, raises `Inexact` for a result needing 29 significant digits, raises `Overflow` for `1e1000000`, permits exact `1e-1000026`, and raises `Underflow` for `1e-1000027`.

Git fetch succeeded, and HEAD was zero commits behind `origin/main`. The active branch is `features`. Existing changes to `.gitignore`, `.idea/`, and `skills-lock.json` belong to the user and are outside this design. Sandbox command startup failed; inspection and checks required approved execution outside that sandbox.
