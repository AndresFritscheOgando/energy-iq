# 0004. Bounded Ollama field proposals

## Summary

The local model suggests invoice fields from retained page text. Its output is a proposal with evidence, never a verified invoice or tariff rule. You can finish manually when the model fails.

## Requirements

- **AC-1**: A provider interface accepts bounded page text and a schema, and returns one typed proposal or a safe failure. A fake provider makes normal tests deterministic. Real Ollama checks are opt in.
- **AC-2**: Each proposed field declares explicit, inferred, or not found, a candidate value, page evidence, and uncertainty. Missing evidence and contradictions are visible. No unsupported numeric value is auto accepted.
- **AC-3**: Pydantic validation and deterministic checks reject invalid dates, units, money, negative kWh, impossible periods, and arithmetic conflicts. Model text cannot change policy, ownership, or tool permissions.
- **AC-4**: Timeouts, invalid JSON, oversized output, missing model, and bounded retries leave the original document and manual draft path intact. No model run modifies a confirmed revision.
- **AC-5**: Record model name, tag or digest, prompt revision, schema revision, token count if available, elapsed time, and safe error code without logging bill content.

## Decision

Use the official Ollama structured output format through a provider adapter. Keep the Pydantic schema small and versioned. Request a proposal for distributor, tariff class, period dates, billed kWh, DOP total, energy charge, and optional issue and due dates. The adapter is local only; the model receives only the authorized document's bounded text. Deterministic code validates all values and evidence after generation.

## Feature design

**Proposal contract**: Each field has `state`, nullable normalized value, nullable raw quote, page number, span, and uncertainty reason. `state` is `explicit`, `inferred`, or `not_found`. Inferred values require review even if they pass type checks. Contradictions remain a list of candidates with evidence; they are not silently resolved by the model. Use exact decimal strings for money and kWh.

**Evidence rule**: A quote is verified only when code finds it in the page text (one exact match) and, for numbers and dates, the quote is one printed line of at most 120 characters that carries the field's unit or label, names one value, and keeps its sign. A kWh value needs `kWh` beside the number; money needs `RD$`, `$` or `DOP` and the field's label (total or energy charge); a period start is the first date of its quote and a period end the last; issue and due dates need their label. Contradiction candidates pass the same checks. A number that merely appears somewhere in a longer quote is not verified.

**Failure contract**: Only transient connection and timeout failures can be retried, with a small fixed attempt cap and jitter. Invalid schema or evidence moves to `needs_review`; provider outage moves to `failed` with manual review still available. Limit input pages, text bytes, output bytes, duration, and concurrent calls. A model must have an explicit capability test for structured output before selection. Record measured hardware and model digest.

**Tests**: Fake provider cases include valid evidence, hallucinated values, prompt injection, foreign ID in text, invalid JSON, extra keys, conflicting totals, absent dates, timeout, and cancellation. The separate local model run reports per field metrics against the versioned corpus.

## Build plan

1. Add versioned proposal schemas and a fake provider, satisfies **AC-1** to **AC-3**.
2. Add local Ollama adapter, limits, safe run states, and metadata, satisfies **AC-4**, **AC-5**.
3. Run deterministic cases and the opt in measured model evaluation, satisfies **AC-1** to **AC-5**.

## Consequences

Structured output reduces parsing errors but cannot make a value true. Every proposal remains subject to evidence checks and human confirmation.

## Rationale

The existing AI design selects local Ollama and a provider interface. The owner chose manual correction during outage or validation failure.
