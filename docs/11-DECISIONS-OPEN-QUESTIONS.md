# Architecture Decisions, Assumptions and Open Questions

## Recorded decisions
- [ADR-001](adr/ADR-001-modular-monolith.md): modular monolith for the portfolio product.
- [ADR-002](adr/ADR-002-local-llm.md): local Ollama and provider abstraction.
- [ADR-003](adr/ADR-003-trust-and-money.md): deterministic authoritative calculations and human-verified bill extraction.
- [ADR-004](adr/ADR-004-full-stack.md): Next.js frontend + FastAPI + PostgreSQL.
- [ADR-005](adr/ADR-005-architect-led-implementation.md): architect-led implementation replaces mentorship and educational delivery gates.

## Open decisions (defer until relevant phase)
1. Session vs token auth implementation details, CSRF and hosting origin setup (P2).
2. Private file storage backend, file scanning choice, OCR/vision model and limits (P4).
3. Official distributor tariff sources, current rate schedule, rate categories, taxes/fees, date semantics (P4). No guesses.
4. Whether readings are captured at exact timestamp or local date-only, and conflict resolution policy (P1).
5. Specific Ollama models and embedding dimensions, selected by tests and machine resources (P4/P6).
6. Which RAG hybrid retrieval approach and indexes warrant complexity (P6).
7. Deployment target and monthly budget (P8). Self-hosted reproducible demo is the default.
8. How to reconcile meter resets and replaced meters where discontinuity is poorly documented (P1).
9. Retention period for original bill files, embedded text and logs (P4/P8).
10. What evidence supports cause-related insights (P5/P6); refrain from causal claims without data.

## Source-of-truth rule
Project docs define intended design, tests define executable outcomes, implementation code is not itself a substitute for design decisions, and official/current distributor documents define real tariffs. Update docs when changing validated behavior.
