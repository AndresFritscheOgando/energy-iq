# Verify: P1-04 time normalized consumption and coverage · spec 0005 · updated 2026-11-03
_Steps derived from spec 0005 acceptance criteria and its Value sourcing table. `/check verify` runs these; `/test` locks the durable ones._

All steps use synthetic UUIDs and values only. Run probes with `uv run python -` from the repo root (pytest config puts `backend/src` on the path; for direct probes set `PYTHONPATH=backend/src`).

## Library probes (manual)
- [x] Three valid intervals 36 hours apart with 10 kWh each → `normalize_intervals` gives `duration == timedelta(hours=36)` and `kwh_per_day == Decimal("6.666667")` (exponent −6) for each, in input order → AC-1
- [x] Change one interval to 20 hours and 5 kWh → its rate becomes `6.000000`, the others stay `6.666667` (rate follows that interval's own elapsed time, not a fixed 24 hours) → AC-1, Value sourcing `kwh_per_day`
- [x] Rate ties over a 24 hour interval: 0.0000005 → `0.000000`, 0.0000015 → `0.000002`, 0.0000025 → `0.000002` (half even, rounded once) → AC-1
- [x] Valid 0 kWh interval → rate `Decimal("0.000000")`; in a summary it counts as covered and creates no gap → AC-1, AC-5
- [x] Invalid (flagged) interval → `kwh_per_day is None` → AC-1
- [x] Pass a non `ConsumptionInterval` item at index 1 to both functions → `TypeError` naming index 1 → AC-2
- [x] Remove the middle interval of a chain (hole), then make two intervals overlap, then mix two meters → each raises `ValueError` naming the index, for both functions → AC-2, Value sourcing "the chain's meter"
- [x] Pass a generator → both functions return full results; input list compares equal before and after → AC-2
- [x] `summarize_consumption` with `meter_id="x"` → `TypeError`; with `OTHER_METER` against this meter's chain → `ValueError` "index 0 belongs to a different meter" → AC-3, Value sourcing `meter_id`
- [x] Naive `window_start`, a −04:00 offset bound, and `window_end <= window_start` → the existing UTC errors and an empty window `ValueError` → AC-3, Value sourcing window bounds
- [x] Chain 0–10, 10–20, 20–30 h with window [10, 20) → only the middle interval is measured; neighbours that touch the bounds create no gap → AC-4
- [x] Window [0, 108) over the 36 hour chain → `measured_kwh == Decimal("30")`, ratio `1.0000`, average `6.666667`, no gaps → AC-4, AC-5, AC-7, Value sourcing `measured_kwh`, `coverage_ratio`, `average_kwh_per_day`
- [x] Shift the window to [−5, 45) over a real `compute_intervals` chain (readings every 10 h, approved reset at 15 h, flagged reading at 30 h) → gaps in order: `before_first_reading` [−5, 0), `invalid_interval` `meter_boundary` with the event ID [10, 20), `invalid_interval` `flagged_reading` [20, 30) and [30, 40), `partial_interval` [40, 45) with reading IDs 5 and 6 → AC-5, AC-6, Value sourcing gap bounds, reasons, copied IDs
- [x] In that same summary, the partial interval's 10 kWh is absent: `measured_kwh == 10`, average `24.000000`, ratio `0.2000` → AC-8, AC-7
- [x] Invalid interval crossing `window_start` → still `invalid_interval`, trimmed to the window, keeps its `interval_reason` and `event_ids` → AC-6
- [x] For every summary above, the measured spans plus gap spans tile `[window_start, window_end)` with no hole or overlap, and `covered + uncovered == window length` → AC-5, Value sourcing `covered`, `uncovered`
- [x] Ratio cases: covered 1 h of 3 h → `0.3333`, 2 h of 3 h → `0.6667`; covered 1 s and 3 s of 20,000 s → `0.0000` and `0.0002` (half even) → AC-7
- [x] Empty chain, window fully before the data, window fully after → zero kWh, zero coverage, `None` average, one whole window gap (`no_intervals`, `before_first_reading`, `after_last_reading`), no exception → AC-7
- [x] Recursively walk a mixed summary's dataclass fields and tuples → no `float` anywhere; durations are `timedelta`, kWh, rates and ratios are `Decimal` → AC-8
- [x] Sum that cannot be held at precision 28 (10²⁷ kWh plus 0.1 kWh) → raises a `DecimalException`, never rounds; a caller context with `prec=2` does not change an exact total → Value sourcing `measured_kwh` policy

## Commands
- [x] `uv run pytest -q -p no:cacheprovider backend/tests/test_reading_normalization.py` → 49 passed → AC-1 to AC-8
- [x] `uv run pytest -q -p no:cacheprovider` → 303 passed → regression
- [x] `uv run ruff check .` and `uv run ruff format --check .` → clean
- [x] `uv run pyright` → 0 errors, 0 warnings

## Acceptance criteria coverage
- AC-1: rate steps 1 to 5 · AC-2: steps 6 to 8 · AC-3: steps 9 and 10 · AC-4: steps 11 and 12 · AC-5: steps 13 and 16 · AC-6: steps 13 and 15 · AC-7: steps 12, 14, 17, 18 · AC-8: steps 14 and 19
- Value sourcing: every row is exercised (rates, chain meter, `meter_id`, window bounds, `measured_kwh` and its policy, `measured_intervals`, gap bounds, reasons, copied IDs, `covered`, `uncovered`, ratio, average).
