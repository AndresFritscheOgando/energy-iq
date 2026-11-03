# 0007 rationale. Meter semantics, discontinuity rules, and operational trade offs

## Context

Phase 1 built the reading domain in four specs: validated records (0002), stable ordering with conflict groups (0003), interval boundaries with typed invalid reasons (0004), and time normalized rates with window coverage (0005). Spec 0006 added property tests over the whole chain. Each spec records its own rules, but nothing explains the model as a whole: what a reading means, when kWh is known, when it must stay unknown, and what that strictness costs in practice. Phase 2 is about to expose these numbers through an API and a database, and every constraint, error code, and UI message there depends on these rules being clear.

Two Phase 1 questions in `docs/11-DECISIONS-OPEN-QUESTIONS.md` are still open. Item 4 asks whether readings carry an exact timestamp or a local date only. The domain already requires a UTC instant and keeps `original_local_date` only as provenance, but no rule says how a date typed by a resident becomes an instant. Item 8 asks how to reconcile resets and replacements that were never properly recorded. Today an unexplained decrease is simply invalid, but no policy says whether that is final or a stopgap.

Two modeling gaps also surfaced while reviewing the code. First, a meter replacement under one meter ID cannot record the old meter's final reading and the new meter's first reading at the same instant, because two readings at one instant are a timestamp conflict that stops interval calculation. The kWh between them is lost by construction. Second, a rollover (a mechanical register wrapping to zero) is always `unsupported_event`, because the domain does not know the register's capacity.

AGENTS.md sets hard constraints: cumulative kWh, no silent treatment of a reset, replacement, rollover, or negative delta as normal consumption, `Decimal` arithmetic, UTC internally with `America/Santo_Domingo` as the UI default, and a deterministic ordering rule for date only readings. Leaving this undocumented means Phase 2 would either rediscover the rules from code or, worse, relax them under API pressure.

## Options considered

### Option 1: Standalone domain reference with tested worked examples, plus targeted decisions

A new numbered document, `docs/12-METER-SEMANTICS.md`, holds the whole model and the trade offs, with a table of worked examples that a dedicated test module mirrors one to one. The open questions are closed in the document and in `11-DECISIONS`, and the one architectural change (replacement as a new Meter) gets ADR-006.

**Pros**:
- One readable place for the model, next to the other numbered docs.
- Tested examples catch drift between the document's numbers and the code.
- Closes the open questions with concrete, checkable rules before P2-04 needs them.

**Cons**:
- A new test module and a new document to maintain.
- Prose rules outside the examples can still drift.

### Option 2: Fold the semantics into `04-DATA-MODEL-API.md`

Add a meter semantics section to the existing data model document and link existing tests.

**Pros**:
- No new file; everything about the data model in one place.
- No new code at all.

**Cons**:
- That file is already dense with contracts; trade off prose and examples would bury them.
- Linked tests do not prove the document's own numbers, so they can go stale unnoticed.

### Option 3: ADR only

Record the decisions as ADR-006 and leave the semantics in the existing specs.

**Pros**:
- Smallest change.
- Decisions are clearly dated and reasoned.

**Cons**:
- ADRs explain why a choice was made; they are a poor reference for rules and examples.
- A reader still has to assemble the model from four specs.

## Rationale

The force that matters most is Phase 2. The API, migrations, and error semantics will be written against whatever the team believes the rules are, so the rules need one home that is readable without the specs and cannot silently disagree with the code. Option 1 is the only option that gives both: a standalone reference, and a test per example that fails if behavior changes. Option 2 saves a file but trades away the drift check and makes the busiest contract document harder to read. Option 3 records decisions but not the model.

The decisions themselves follow the AGENTS.md constraints. Keeping cumulative data canonical and incremental data separate avoids inventing an anchor value, which would be a silent estimate. Keeping undocumented decreases strict follows "do not silently treat a reset ... as normal consumption" directly; a heuristic that guesses a reset when a value is near zero would do exactly that. Rollover stays unsupported because the formula needs a register capacity the domain does not have, and adding that field is a Phase 2 schema decision. Replacement as a new Meter is the only way to keep both chains continuous without breaking the conflict rule from spec 0003, which is why it earns an ADR. Noon local for date only readings minimizes misordering against same day timestamped readings, and `America/Santo_Domingo` has no daylight saving time, so the conversion is always exactly 16:00 UTC. Spikes stay valid because no threshold has evidence behind it, and Phase 5 already owns anomaly scoring against a contextual baseline.
