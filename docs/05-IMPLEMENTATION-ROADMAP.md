# Implementation Phases, Delivery Gates, and Deliverables

**Rule:** each phase must finish with running tests, a README update, demonstrated behavior, and code review. The architect implements complete features and tests directly. Advance within the authorized scope when technical gates pass; no teaching or conceptual assessment is required. These are sequence gates, not promised calendar durations.

| Phase | Theme | Implementation scope | Exit gate |
|---|---|---|---|
| 0 | Deterministic foundations & CLI | environment, consumption validation, Decimal, UTC elapsed time, basic observation sorting, CLI | valid reading deltas, ordering and CLI behavior, edge-case tests |
| 1 | Reading history domain | typed reading/event models, stable sorting, duplicates, discontinuities, interval math | correct interval and coverage handling |
| 2 | FastAPI + persistence + auth | endpoints, DTOs, SQLAlchemy queries, migrations, ownership, local database infrastructure | isolated REST CRUD, migrations, integration tests |
| 3 | Next.js product UI | typed API client, charts, forms, accessibility, error states | create property/meter/readings end-to-end |
| 4 | Bill intelligence | safe ingestion, parsing/vision, provider adapter, structured extraction, human review, tariffs/reconciliation | extraction dataset, review trail, tariff tests |
| 5 | Forecasting/anomaly | baselines, feature engineering, forecasts, backtesting, leakage prevention, evaluation harness | baseline comparison, documented error and uncertainty |
| 6 | RAG + energy assistant | provider interfaces, chunks, embeddings, scoped retrieval, citations, tool facts, grounded responses | RAG evals, unauthorized-data prevention |
| 7 | Agents + MCP | tool schemas, permission boundaries, approvals, MCP server/client | tool tests, negative security cases, logs |
| 8 | Production & portfolio | deployment, OpenTelemetry, CI, threat model, runbooks, demo/docs | full smoke tests, reproducible demo, honest benchmarks |

## Phase 0 tickets
- P0-01 Configure Python and `uv`, the local environment, dependency lockfile, and test runner; verify versions.
- P0-02 Implement a function accepting two cumulative kWh readings; validate negative and reversed values.
- P0-03 Use `Decimal` for exact consumption arithmetic and test fractional cases.
- P0-04 Implement UTC elapsed-time validation and basic chronological observation ordering, with explicit equality behavior and tests.
- P0-05 Build a CLI that asks for two values, prints kWh, handles input errors; no full-feature framework.
- P0-06 Review and harden Phase 0 code, run required checks, update documentation, and record verified delivery status. Commit when requested and Git is available.

## Phase 1 tickets
- P1-01 Define reading and meter event models using type hints/dataclasses.
- P1-02 Implement stable sorting and duplicate detection.
- P1-03 Compute intervals from ordered readings, with reset/replacement boundary rules.
- P1-04 Compute time-normalized consumption; characterize missing intervals.
- P1-05 Property-based/invariant tests as optional advanced challenge.
- P1-06 Document cumulative vs incremental meter semantics, discontinuity rules, and operational trade-offs.

## Phase 2 tickets
- P2-01 Implement the minimal FastAPI application with request/response schemas and explicit HTTP error semantics.
- P2-02 Add PostgreSQL Compose service, SQLAlchemy mappings, Alembic migration; justify constraints.
- P2-03 Add authenticated ownership context and property/meter CRUD.
- P2-04 Add readings API with transaction and idempotency behavior.
- P2-05 Test cross-user access, duplicate request, migration upgrade/downgrade.

## Phase 3 tickets
- P3-01 Next.js setup, typed API layer and session strategy.
- P3-02 Property selector, meter creation and readings form.
- P3-03 Consumption trends/chart with empty, partial and error states.
- P3-04 Accessibility/interaction tests and end-to-end seed demo.

## Phase 4 tickets
- P4-01 Manual invoice entry and source preservation.
- P4-02 Safe file upload and extraction job lifecycle.
- P4-03 PDF native text parsing; evaluate OCR/vision fallback.
- P4-04 Introduce Ollama behind strict structured extraction contract.
- P4-05 Build human corrections and provenance UI.
- P4-06 Effective-dated tariff rules with official sources; reconciliation and test fixtures.

## Phase 5 tickets
- P5-01 Define business forecast target and data resolution.
- P5-02 Naive lag/seasonal baseline; time-based data splits.
- P5-03 Train/evaluate optional statistical/ML baseline without future leakage.
- P5-04 Anomaly score versus contextual baseline; false-positive analysis.
- P5-05 Dashboard uncertainty, baseline metric comparison and limitations.

## Phase 6 tickets
- P6-01 Extend provider interfaces for assistant inference, context/output budgets, timeouts, and usage limits.
- P6-02 Integrate and benchmark embeddings and similarity retrieval on synthetic fixtures.
- P6-03 Chunk authorized documentation with page offsets and metadata.
- P6-04 Exact pgvector search with mandatory user/property filters; benchmark relevance.
- P6-05 Add grounded response generation using separately computed numeric facts.
- P6-06 Evaluate hallucination, citation support and abstention; adversarial docs.

## Phase 7 tickets
- P7-01 Build two read-only tools: `get_consumption_summary`, `list_verified_bills`.
- P7-02 Implement bounded agent loop with time/tool budget, audit and allowlist.
- P7-03 Build an approval-requiring draft action; never autonomously modify canonical readings.
- P7-04 Expose authorized read-only tools via official MCP SDK; implement simple MCP client.
- P7-05 Threat-test cross-tenant access, prompt injection, tool argument tampering.

## Phase 8 tickets
- P8-01 CI checks (format, typing, tests, vulnerability checks).
- P8-02 Structured logs/metrics/traces for API, jobs, model and tools.
- P8-03 Harden deployment: secrets, database backups, encryption, health and resource constraints.
- P8-04 Performance tests, disaster restore exercise and failure simulations.
- P8-05 Portfolio demo: synthetic dataset, annotated screenshots, architecture, ADRs, evaluation table and resume bullets reflecting only shipped features.

## Delivery acceptance

- Implement the ticket's specified behavior and edge cases with meaningful automated tests.
- Pass applicable formatting, lint, typing, integration, and evaluation checks for the phase; record actual commands/results and any checks not run.
- Review ownership, privacy, deterministic calculations, failure behavior, and architectural boundaries where relevant.
- Update progress and affected specifications or ADRs. Do not mark unresolved defects complete.
- Preserve phase order and existing product security approvals. Continue implementation within the authorized scope when the technical gate passes.
- Historical quizzes, mastery ratings, and learner-written-code requirements no longer govern delivery; see [the engineering contract](09-ENGINEERING-CONTRACT.md).
