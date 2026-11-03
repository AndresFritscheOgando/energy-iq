# Verify: P1-06 meter semantics · spec 0007 · updated 2026-11-03
_Steps derived from spec 0007 acceptance criteria. `/check verify` runs these; `/test` locks the durable ones._

## Document review
- [ ] Open `docs/12-METER-SEMANTICS.md` → the eleven sections appear in this order: Purpose; Cumulative readings; Incremental readings; Time and ordering; Discontinuity rules; Meter events; Undocumented decreases; Time normalization and coverage; Operational trade offs; Worked examples; Out of scope and future work → AC-1
- [ ] Find links to `12-METER-SEMANTICS.md` in `README.md` (docs table), `docs/04-DATA-MODEL-API.md` (Meter entity area and invariant 3), `docs/11-DECISIONS-OPEN-QUESTIONS.md`, and the roadmap P1-06 entry → all four present → AC-1
- [ ] Cumulative readings section states `Decimal`, at most 6 fractional places, range `0` to `999999999999.999999`; compare with `_MAX_READING` and `_MAX_FRACTIONAL_PLACES` in `readings/models.py` → match → AC-2
- [ ] Incremental readings section states incremental data is never turned into synthetic cumulative readings, and that Phase 4 compares bill kWh against a window summary without merging → AC-2
- [ ] Discontinuity table has one row per `IntervalReason` member plus the valid row; compare the member list with `IntervalReason` in `readings/intervals.py` and the precedence text with `_event_reason` and the `compute_intervals` branch order → match exactly → AC-3
- [ ] Event timing rule reads `previous.recorded_at < effective_at <= current.recorded_at`; compare with the two `while` loops in `compute_intervals` → match → AC-3
- [ ] Meter events table covers all five `MeterEventType` members with today and planned handling; rollover formula is `(10^digits − previous) + current`, valid only for an approved event and a result below `10^digits` → AC-4
- [ ] `docs/adr/ADR-006-meter-replacement-new-record.md` exists with Status Accepted, Date, Context, Decision, Consequences, Revisit trigger → AC-4
- [ ] `docs/11-DECISIONS-OPEN-QUESTIONS.md`: open list no longer has the date only item or the poorly documented reset item, is numbered 1 to 8 without gaps, and Recorded decisions has ADR-006 plus both decisions with links → AC-5
- [ ] Date only rule states 12:00 `America/Santo_Domingo`, 16:00 UTC, `original_local_date` as provenance, applied in P2-04, same instant gives a conflict. Vary the source (Windows has no IANA database, so `--with tzdata` adds one only for this command): `uv run --with tzdata python -c "from datetime import datetime; from zoneinfo import ZoneInfo; print(datetime(2026,6,15,12,tzinfo=ZoneInfo('America/Santo_Domingo')).utcoffset(), datetime(2026,12,15,12,tzinfo=ZoneInfo('America/Santo_Domingo')).utcoffset())"` → both `-1 day, 20:00:00` (UTC−4 in summer and winter, so always 16:00 UTC) → AC-5
- [ ] Normalization section states 86,400 UTC seconds per day, rounding once half even to 6 places, half open window, no proration, `partial_interval` gap; compare with `RATE_PLACES`, `RATIO_PLACES`, `_MICROSECONDS_PER_DAY`, and the `inside` check in `readings/normalization.py` → match → AC-6
- [ ] Operational trade offs covers all seven topics: strictness, cadence, reset and replacement capture practice, late readings, manual versus imported, spikes (Phase 5, P5-04), measured below bill total → AC-6
- [ ] Worked examples table numbers match `docs/specs/0007-meter-semantics-discontinuity-rules/index.md` and `backend/tests/test_meter_semantics_examples.py` value for value → AC-7

## Commands
- [ ] `uv run pytest backend/tests/test_meter_semantics_examples.py -q -p no:cacheprovider` → 13 passed → AC-7
- [ ] `grep -c "^def test_e[0-9]*_" backend/tests/test_meter_semantics_examples.py` → 13, and the IDs are exactly e1 to e13, one each → AC-7
- [ ] `grep -n "^from energyiq" backend/tests/test_meter_semantics_examples.py` → only `from energyiq.readings import` → AC-7
- [ ] Mutation probe on a scratch copy: change `<=` to `<` in the second event loop of `compute_intervals` → `test_e5`, `test_e6`, `test_e7` fail; change the `inside` check to allow crossing intervals → `test_e11` fails; revert, then `git diff backend/src` is empty → AC-3, AC-6, AC-7
- [ ] `git status --short backend/src` → no output (no application source changed) → AC-7
- [ ] `uv run pytest -q -p no:cacheprovider` → 325 passed → AC-8
- [ ] `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` → all clean → AC-8
- [ ] Local link check over the changed docs → every link added in P1-06 resolves, including `#date-only-readings-decided-applied-in-phase-2-p2-04` and `#undocumented-decreases`; links to the absent specs 0001 to 0004 and task files are a known pre existing gap → AC-1
- [ ] `docs/PROGRESS.md` and the roadmap record P1-06 with the checks run and the Phase 1 gate as passed, citing `docs/specs/0006-reading-chain-property-tests/verify.md` → AC-8

## Acceptance-criteria coverage
- AC-1 covered by document review steps 1 and 2 and the link check
- AC-2 by document review steps 3 and 4
- AC-3 by document review steps 5 and 6 and the mutation probe
- AC-4 by document review steps 7 and 8
- AC-5 by document review steps 9 and 10
- AC-6 by document review steps 11 and 12 and the mutation probe
- AC-7 by document review step 13 and command steps 1 to 5
- AC-8 by command steps 6, 7, and 9
