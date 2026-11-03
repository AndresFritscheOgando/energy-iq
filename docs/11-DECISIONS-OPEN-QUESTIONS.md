# Architecture Decisions, Assumptions and Open Questions

## Recorded decisions
- [ADR-001](adr/ADR-001-modular-monolith.md): modular monolith for the portfolio product.
- [ADR-002](adr/ADR-002-local-llm.md): local Ollama and provider abstraction.
- [ADR-003](adr/ADR-003-trust-and-money.md): deterministic authoritative calculations and human-verified bill extraction.
- [ADR-004](adr/ADR-004-full-stack.md): Next.js frontend + FastAPI + PostgreSQL.
- [ADR-005](adr/ADR-005-architect-led-implementation.md): architect-led implementation replaces mentorship and educational delivery gates.
- [ADR-006](adr/ADR-006-meter-replacement-new-record.md): from Phase 2, a meter replacement creates a new Meter record instead of continuing one chain.
- Date only readings (formerly open item 4, decided 2026-11-03): the domain keeps requiring an exact UTC instant; the P2-04 API boundary converts a date only reading to 12:00 `America/Santo_Domingo` on that date (16:00 UTC) and keeps `original_local_date` as provenance; same instant readings go through the P1-02 conflict flow. See [meter semantics](12-METER-SEMANTICS.md#date-only-readings-decided-applied-in-phase-2-p2-04).
- Poorly documented resets and replacements (formerly open item 8, decided 2026-11-03): a decrease without an approved event stays `unexplained_decrease` with no kWh until a person records and approves a reset or replacement event; the system never infers the cause. See [meter semantics](12-METER-SEMANTICS.md#undocumented-decreases).

## Open decisions (defer until relevant phase)
1. Session vs token auth implementation details, CSRF and hosting origin setup (P2).
2. Private file storage backend, file scanning choice, OCR/vision model and limits (P4).
3. Official distributor tariff sources, current rate schedule, rate categories, taxes/fees, date semantics (P4). No guesses.
4. Specific Ollama models and embedding dimensions, selected by tests and machine resources (P4/P6).
5. Which RAG hybrid retrieval approach and indexes warrant complexity (P6).
6. Deployment target and monthly budget (P8). Self-hosted reproducible demo is the default.
7. Retention period for original bill files, embedded text and logs (P4/P8).
8. What evidence supports cause-related insights (P5/P6); refrain from causal claims without data.

## Source-of-truth rule
Project docs define intended design, tests define executable outcomes, implementation code is not itself a substitute for design decisions, and official/current distributor documents define real tariffs. Update docs when changing validated behavior.
