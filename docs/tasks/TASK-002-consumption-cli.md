# Task 002 - Local Consumption CLI

**Phase:** 0. **Ticket:** P0-05. **Story:** US-001.

## Contract
- Run `python -m energyiq` with `backend/src` on `PYTHONPATH`; no additional packages or build configuration are required.
- Prompt for previous and current cumulative readings in kWh. Strip surrounding whitespace and construct Decimal values directly from input strings.
- Accept decimal-point notation and valid Decimal exponent notation. Reject empty or malformed values, comma separators, NaN (including signaling NaN), and infinities.
- Delegate negative/decreasing-reading validation and consumption arithmetic to `calculate_consumption`; equal readings produce zero consumption.
- Print `Consumption: <value> kWh` to stdout and exit with status 0 on success. Preserve Decimal output, including fractional precision; do not convert through float.
- Report input/domain/arithmetic errors on stderr with status 2 and no consumption result. Exhausted input also returns status 2; Ctrl+C returns status 130 with a cancellation message.
- Perform one calculation per invocation. Fail clearly without retrying or printing a traceback for handled input errors.
- Importing calculation, CLI, or module-entry-point code must not print output or prompt for input.
- Keep execution local and ephemeral: no file/database persistence, external calls, personal account details, or authorization-sensitive operations.

## Acceptance cases
Cover integer, equal, zero, fractional, whitespace-padded, malformed, empty, comma-separated, non-finite, negative, and decreasing inputs. Check invalid values in either input position. Verify decimal arithmetic overflow, EOF, and cancellation at either prompt.

Exercise the actual module entry point in subprocesses to confirm prompts, exact fractional results, stderr messages, process exit status, and absence of import side effects.

## Verification
Completed on 2026-11-02. The full suite passed 80 tests, including 38 new CLI cases. Ruff lint and formatting passed for eight Python files. Actual commands/results are recorded in [progress](../PROGRESS.md).

## Limits and next task
The source package still uses `PYTHONPATH`; distributable packaging and an installed shell command are outside this ticket. Domain-level non-finite/type hardening and the final Phase 0 review remain P0-06 work. The CLI validates finite inputs before calling the existing calculation function.
