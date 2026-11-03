# Verify: P1-05 reading chain property tests · spec 0006 · updated 2026-11-03
_Steps derived from spec 0006 acceptance criteria and its Value sourcing table. `/check verify` runs these; `/test` locks the durable ones._

## Commands
- [x] `grep -A6 "dependency-groups" pyproject.toml` → `hypothesis>=6.170` in `dev`; `[project] dependencies = []` → AC-1
- [x] `grep -A1 '^name = "hypothesis"' uv.lock` → a locked `6.170.x` version (6.170.14 at build) → AC-1
- [x] `grep -n "hypothesis" .gitignore` → `.hypothesis/` listed → AC-1
- [x] Read `backend/tests/conftest.py` → `energyiq` (200, derandomize, `database=None`, `deadline=None`, `print_blob=True`) and `deep` (2000, random, default database, `deadline=None`, `print_blob=True`), both with `parent` set to the built in default, and no `suppress_health_check` anywhere → AC-1
- [x] `uv run pytest backend/tests/test_reading_properties.py -q -p no:cacheprovider` twice → 9 passed both times; no `.hypothesis/examples/` folder appears (only `constants/`, a source cache) → AC-1 (profile name, example count, derandomize, database)
- [x] `CI=1 uv run pytest backend/tests/test_reading_properties.py -q -p no:cacheprovider --hypothesis-show-statistics` → still `max_examples=200`, so the `ci` profile did not take over → AC-1 (profile name source)
- [x] `ENERGYIQ_HYPOTHESIS_PROFILE=nope uv run pytest -q -p no:cacheprovider` → session stops with `InvalidArgument: Profile 'nope' is not registered`, no tests run → AC-1
- [x] `ENERGYIQ_HYPOTHESIS_PROFILE=deep uv run pytest backend/tests/test_reading_properties.py -q -p no:cacheprovider --hypothesis-show-statistics` → 9 passed, statistics show `max_examples=2000` → AC-1
- [x] Ordering properties pass: `-k "permutation or conflicts or ordered_result or input_order or iterator"` → 5 passed → AC-2 (expected order and groups derived from input indices)
- [x] `-k "pair_rules or collision"` → 2 passed → AC-3 (pair set from consecutive non voided readings, `event_ids` from `previous < effective_at <= current`, spec 0004 precedence restated)
- [x] `-k tiles` → 1 passed → AC-4 (measured set and kWh under `exact_kwh_context()`, ratio and average via the test local half even helper, no private `_round_once`)
- [x] `-k adjacent` → 1 passed → AC-5 (crossing set X from interior cuts, identity by `(previous_reading_id, current_reading_id)`)
- [x] `grep -nE "assume\(|\.filter\(|suppress_health_check|_round_once|ConsumptionInterval\(" backend/tests/test_reading_properties.py` → no matches (no rejection sampling, no hand built intervals, no private calls) → AC-4, AC-5, AC-6
- [x] Generator coverage probe (scratch script over `window_cases()` and `reading_lists()`, 400 cases) → nonzero counts for every `IntervalReason`, collisions, exact duplicate objects, 1 µs intervals, events on reading instants, empty chains, windows before, after, and covering the data, and bounds on and 1 µs off boundaries → AC-6
- [x] Mutation check (by hand, revert after each): in `normalization.py` change `inside` to `interval.start > window_start ...` → tiling and additivity fail with a small shrunk chain; in `ordering.py` sort ties by `-input_index` → three ordering properties fail. `git diff backend/src` empty afterward → AC-2, AC-4, AC-5, AC-6
- [x] `uv run pytest -q -p no:cacheprovider --durations=0` → 312 passed; the property file's call times total 15 s or less (6.5 s at build) → AC-7
- [x] `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` → all clean → AC-7

## Acceptance-criteria coverage
- AC-1 covered by the first eight command steps · AC-2 by the ordering step and mutation step · AC-3 by the pair rules step · AC-4 by the tiling, grep, and mutation steps · AC-5 by the additivity, grep, and mutation steps · AC-6 by the grep, probe, and mutation steps · AC-7 by the last two steps (no defect found, so no pinned `@example` is expected)
