# 0006. Rationale: property based invariant tests

Decision record for [index.md](index.md). `/develop` builds from the index. This file explains why.

## Context

P1-02 to P1-04 built three pure functions that chain together: `order_readings` (stable ordering and conflict groups), `compute_intervals` (valid and invalid intervals with event, flag, and decrease rules), and `summarize_consumption` (measured kWh and typed gaps over a half open window). Their unit tests (303 in the suite) use hand built fixtures. The P1-04 verification checked tiling on 12 summaries. Those cover the documented cases well, but the contracts make universal promises: every chain, every window, no hole, no overlap, no double count. A promise about every input is checked weakly by a dozen chosen inputs.

The risky shapes are rare by nature: a window bound exactly on a reading instant, an event exactly on a reading, a 1 µs interval, a voided reading next to a flagged one, a decrease right after an approved reset. These are the inputs where `<` versus `<=` mistakes hide. Phase 2 will expose these numbers through an API and Phase 3 will chart them. A double count or a hidden hole found after that point costs much more than one found now.

There are constraints. AGENTS.md says to add a dependency only when the phase needs it, after checking official docs and compatibility, and the roadmap ticket asks for that call to be made explicitly. Tests must be deterministic. The project runs Python 3.13 with uv, strict Pyright over tests, and `--import-mode=importlib`. The suite runs locally on Windows, with no CI pipeline yet.

## Options considered

### Option 1: Hypothesis (dev group only)

Use the standard Python property testing library. Strategies build real domain records, and the library shrinks a failing input to a minimal one.

**Pros**:
- Shrinking: a failure in a long chain reduces to the two or three readings that matter.
- It ships mature `datetimes`, `decimals(places=...)`, and `@composite` strategies, plus `@example` for pinning regressions.
- Settings profiles give a reproducible default (`derandomize=True`, `database=None`) and a deeper opt in run, with no custom code.
- It is typed (`Typing :: Typed`), so strict Pyright over tests keeps working.

**Cons**:
- A new dev dependency that releases often. An upgrade can change which examples the derandomized run tries.
- Its own concepts to learn (strategies, health checks, profiles).

### Option 2: Stdlib seeded random generators

Write generators on `random.Random(seed)` and loop over a fixed list of seeds.

**Pros**:
- No new package. Fully deterministic and easy to read.

**Cons**:
- No shrinking. A failing seed hands you a 30 reading chain to cut down by hand.
- We would write and maintain the generator, boundary biasing, and replay plumbing ourselves, and that is exactly the code Hypothesis already gets right.

### Option 3: Exhaustive enumeration of small chains

Enumerate every chain up to N readings over a tiny grid of times, values, statuses, and events.

**Pros**:
- No dependency. It proves the rules completely within the grid, which is the strongest kind of guarantee there.

**Cons**:
- Combinatorial blow up limits N to about 4 or 5 readings, and the grid misses microsecond timing, large values, and rounding ties.
- The grid has to be redesigned whenever a status or event type is added.

### Option 4: Hypothesis plus an exhaustive boundary grid

Option 1, plus a small exhaustive grid for the boundary touching cases.

**Pros**:
- The best coverage of the exact bound cases.

**Cons**:
- Two harnesses to maintain. Boundary biased strategies (AC-6) already make those cases common, so the grid adds little.

## Rationale

Option 1 wins on the force that matters most: these invariants fail in rare shapes, and the cost of a property test is debugging the failures it finds. Without shrinking (Option 2), every failure becomes a manual bisection. Exhaustive enumeration (Option 3) is attractive for proof, but it cannot reach the microsecond and rounding edges where P1-04 is most delicate. The dependency rule in AGENTS.md is satisfied: Hypothesis is dev only, so it never enters `[project] dependencies` or the runtime. The docs check confirmed Python 3.13 support and the settings API this spec relies on. It is boring, proven tooling, the de facto standard for this job in Python.

Determinism is handled by profiles, not by giving up randomness entirely. The default `energyiq` profile is derandomized with no database, so a red run always means a code change, which honors the deterministic tests rule. `deep` exists for wider searches on demand. The project loads the profile explicitly from its own env var. That way Hypothesis's automatic `ci` profile (enabled by any `CI` variable) cannot make a CI run behave differently from a local one.

For the interval rules, per pair rule checks beat a reference model. A reference model is a second copy of the same algorithm, and copies tend to share misreadings of the spec. Rule statements read like spec 0004 itself and fail with a precise message. For additivity, the exact law (with the crossing set correction) was chosen over disjointness alone, because disjointness cannot detect a summary that silently drops an interval, while the exact equation catches both double counting and loss.

## References

**Project sources**:
- `AGENTS.md`: the dependency rule (add only when the phase requires it, after checking official docs), deterministic tests, and synthetic data only.
- `docs/05-IMPLEMENTATION-ROADMAP.md`: the P1-05 ticket wording.
- `docs/07-TESTING-EVALUATIONS.md`: the deterministic acceptance matrix, including "partially overlapping intervals not double counted".
- Spec 0003 (ordering), spec 0004 (interval rules and precedence), spec 0005 (tiling, gaps, and single rounding).
- `pyproject.toml`, `pyrightconfig.json`: the uv dev group, `--import-mode=importlib`, and strict Pyright over tests.

**Practices & standards**:
- Property based testing with shrinking.
- Deterministic test suites, with randomized exploration kept separate and opt in.
- Rule checks instead of reference models, to avoid a second implementation that shares the same mistakes.

**Links** (web verified on 2026-11-03):
- Hypothesis on PyPI (6.170.14, Oct 30 2026, requires Python >=3.11, classifiers include 3.13 and `Typing :: Typed`): https://pypi.org/project/hypothesis/
- Hypothesis API reference (settings: `max_examples`, `derandomize`, `database`, `deadline`, `print_blob`, `register_profile`, `load_profile`, the built in `ci` profile, `@example`): https://hypothesis.readthedocs.io/en/latest/reference/api.html
- Hypothesis strategies reference (`datetimes(timezones=...)`, `decimals(places=...)`, `composite`): https://hypothesis.readthedocs.io/en/latest/reference/strategies.html
