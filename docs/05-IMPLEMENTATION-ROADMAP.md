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

Phase 0 gate passed on 2026-11-02: 166 tests, Ruff lint, and Ruff formatting passed.
The final review covered every Phase 0 source and test file. Exact arithmetic,
runtime validation, UTC ordering, and real CLI subprocess behavior are verified.
See [progress](PROGRESS.md) for commands, evidence, and remaining limits.

- P1-01 Complete on 2026-11-03: validated typed reading and meter event dataclasses, 217 passing tests, Ruff checks and explicit project Pyright check passed. See [spec 0002](specs/0002-reading-meter-event-models.md).
- P1-02 Complete on 2026-11-03: stable typed reading ordering and complete duplicate timestamp conflict groups. Further contract tests brought the full suite to 231 passing tests. See [spec 0003](specs/0003-reading-order-conflicts.md).
- P1-03 Complete on 2026-11-03: pure interval calculation from conflict free ordered readings, with explicit valid and invalid results for resets, replacements, unapproved or unsupported events, flagged readings, and unexplained decreases. Full suite 254 passed after further boundary tests; Ruff and explicit project Pyright passed. See [spec 0004](specs/0004-reading-interval-boundaries/index.md).
- P1-04 Complete on 2026-11-03: per interval kWh per day from exact elapsed time, and an exact window summary with measured kWh, coverage, average rate, and typed gaps; no estimation or floats. 49 new tests; full suite 303 passed. Ruff and Pyright passed. `/check verify` passed all eight acceptance criteria, and a fresh model review approved it with nits ([review](reviews/2026-11-03-features-p1-04.md)). See [spec 0005](specs/0005-time-normalized-consumption-coverage/index.md).
- P1-05 Complete on 2026-11-03: Hypothesis property tests (dev only dependency) over generated reading and interval chains for ordering stability, interval boundary rules, exact window tiling, and additivity across 2 to 5 adjacent windows. 9 properties at 200 derandomized examples each; full suite 312 passed; about 6.4 s added. No defect found; hand mutation checks were each caught. `/check verify` passed all seven acceptance criteria. See [spec 0006](specs/0006-reading-chain-property-tests/index.md).
- P1-06 Complete on 2026-11-03: the [meter semantics reference](12-METER-SEMANTICS.md) covers cumulative versus incremental data, the discontinuity table and precedence, meter events now and later, the undocumented decrease policy, normalization and coverage, operational trade offs, and worked examples E1 to E13, each mirrored by one test in `backend/tests/test_meter_semantics_examples.py`. Closed open questions 4 (date only readings) and 8 (undocumented decreases) and recorded [ADR-006](adr/ADR-006-meter-replacement-new-record.md) (replacement creates a new Meter record). No application source changed. Full suite 325 passed; Ruff, format, and Pyright passed. `/check verify` passed all 22 steps in its [verification record](specs/0007-meter-semantics-discontinuity-rules/verify.md). See [spec 0007](specs/0007-meter-semantics-discontinuity-rules/index.md).

Phase 1 gate passed on 2026-11-03: correct interval and coverage handling is implemented and tested (P1-01 to P1-05 each passed `/check verify`; P1-05 under [spec 0006](specs/0006-reading-chain-property-tests/verify.md)), and the semantics are documented with tested examples (P1-06). Full suite 325 passed; Ruff, format, and Pyright passed.

## Phase 2 tickets
- P2-01 Implement the minimal FastAPI application with request/response schemas and explicit HTTP error semantics. Built 2026-11-04 from [spec 0008](specs/0008-minimal-fastapi-application/index.md): `GET /health` and stateless `POST /api/v1/consumption/summary`, problem details errors, request ids, JSON access log, body caps, settings, CORS, OpenAPI snapshot. `/check verify` passed 2026-11-04 on a live server (all 13 acceptance criteria, judged with the spec 0009 amendments); spec 0008 Accepted.
- P2-02 Add PostgreSQL Compose service, SQLAlchemy mappings, Alembic migration; justify constraints. Designed 2026-11-04 in [spec 0009](specs/0009-phase-two-persistence-auth/index.md), child [0001](specs/0009-phase-two-persistence-auth/0001-database-foundation.md). Built 2026-11-04: Compose PostgreSQL 18.6, two roles, revision `0001` with named constraints and column grants, `GET /health/ready`, savepoint test fixtures. `/check verify` passed 2026-11-04 (all 9 ACs).
- P2-03 Complete on 2026-11-04: authenticated ownership context and property/meter CRUD. Designed in [spec 0009](specs/0009-phase-two-persistence-auth/index.md), child [0002](specs/0009-phase-two-persistence-auth/0002-identity-properties-meters.md); built with revision `0002`. `/check verify` passed all 12 acceptance criteria and all 38 child checklist steps. The database required suite passed 754 tests.
- P2-04 Built and verified on 2026-11-04: readings API, events, idempotent POSTs, and stored consumption with revision `0003`. The fresh [review](reviews/2026-11-04-features-p2-04.md) found two stored consumption defects (outside history window gaps against child [0003](specs/0009-phase-two-persistence-auth/0003-readings-events-api.md) AC-9, and mixed snapshots under concurrent corrections). Both are fixed, and the `/check verify` rerun passed on a live server.
- P2-05 Test cross-user access, duplicate request, migration upgrade/downgrade. Designed 2026-11-04 in [spec 0009](specs/0009-phase-two-persistence-auth/index.md), child [0004](specs/0009-phase-two-persistence-auth/0004-phase-two-gate-tests.md). Built 2026-11-04: route enumerated cross user, list isolation, unauthenticated and CSRF matrices; committed concurrency tests with forced lock overlap; migration round trips and app role privilege tests on scratch databases. Gate run `ENERGYIQ_REQUIRE_DB=1 uv run pytest`: 881 passed, no skips; without a database: 632 passed, 249 skipped. `/check verify` not run. `/check verify` passed 2026-11-04.

Umbrella spec 0009 step 5 done on 2026-11-04: [ADR-007](adr/ADR-007-session-auth-same-origin-proxy.md) recorded, open decision 1 closed, catalogs current, OpenAPI snapshot matches the app. The Phase 2 technical exit gate holds: owner isolated REST CRUD (cross user matrix), clean migration round trips, and integration tests against real PostgreSQL (`ENERGYIQ_REQUIRE_DB=1`: 881 passed).

Phase 2 gate passed on 2026-11-04: owner isolated REST CRUD (route enumerated cross user, unauthenticated, and CSRF matrices), clean migration upgrade and downgrade round trips, and integration tests against real PostgreSQL. The fresh model [code review](reviews/2026-11-04-features-phase-2.md) approved with nits; its three minors were fixed in `1c4078b`. `ENERGYIQ_REQUIRE_DB=1 uv run pytest`: 889 passed; without a reachable database: 632 passed, 257 skipped with the reason printed. Ruff lint and format and Pyright passed. The P2-01 review minors were closed the same day.

## Phase 3 tickets
- P3-01 Next.js setup, typed API layer and session strategy. Complete 2026-11-05 from [spec 0010](specs/0010-nextjs-foundation-session/index.md), now Accepted. Its [verification record](specs/0010-nextjs-foundation-session/verify.md) is fully checked, including AC-14 and AC-18. The fresh model [rereview](reviews/2026-11-05-features-p3-01-rereview.md) and [scheme header review](reviews/2026-11-05-features-proxy-proto.md) approved with nits. The current tree passed the live AC-18 echo probe again on 2026-11-05. [ADR-008](adr/ADR-008-frontend-data-access.md) records the proxy coverage invariant.
- P3-02 Property selector, meter creation and readings form. Built 2026-11-05 from [spec 0011](specs/0011-product-ui-readings-consumption/index.md), child [0001](specs/0011-product-ui-readings-consumption/0001-properties-meters-readings.md). The warning focus race found by `/check verify` was fixed with a deterministic regression test. The live browser suite and frontend tests passed after the fix; fresh review remains.
- P3-03 Consumption trends/chart with empty, partial and error states. Built 2026-11-05 from [spec 0011](specs/0011-product-ui-readings-consumption/index.md), child [0002](specs/0011-product-ui-readings-consumption/0002-consumption-chart.md). The live browser suite passed after the focus fix; fresh review remains.
- P3-04 Accessibility/interaction tests and end-to-end seed demo. Built 2026-11-05 from [spec 0011](specs/0011-product-ui-readings-consumption/index.md), child [0003](specs/0011-product-ui-readings-consumption/0003-accessibility-e2e-demo.md). The live browser suite passed 56 cases after the focus fix; fresh review remains.

## Phase 4 tickets
Design: [spec 0012](specs/0012-phase-four-bill-intelligence/index.md) entered In Progress on 2026-11-05. P4-01 has been built and checked, while the Phase 3 fresh review is still needed before Phase 4 becomes the current implementation phase.
- P4-01 Manual invoice entry and source preservation. Built 2026-11-05: revision `0004`, owner scoped API, meter page review, exact Decimal values, audit and retry keys, PostgreSQL overlap protection, and a live browser journey. Follow up built 2026-11-05: `POST /invoices/{id}/revisions` now takes a required `base_revision_id`, appends a draft revision to an unconfirmed or open draft invoice, and rejects a stale base with 409, so a partial draft is completed in steps; the meter page has an Edit draft form.
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
