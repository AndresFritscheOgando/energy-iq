# Product Requirements Document — EnergyIQ RD

## Purpose
A self-hostable portfolio-grade energy intelligence web app for Dominican residents and property managers to understand electricity usage and electricity bills. **Not** an official utility portal, utility account integrator, fault diagnosis system, or billing authority.

## Users and jobs-to-be-done
- **Resident/owner**: record cumulative meter readings; quantify daily/interval kWh; compare bills; spot changes; explain why spending differs.
- **Multi-property user**: keep properties and meters separate, view trends per meter and aggregate with safe comparability rules.
- **Reviewer/analyst** (same authenticated account initially): review extracted bill fields, corrections and AI evidence.
- **Developer / evaluator**: reproduce demo, run quality checks, inspect traces and model failures.

## Outcomes (validated in stages)
- Accurate deterministic interval consumption given valid readings.
- Traceable comparisons from verified documents and readings.
- Faster bill entry from human-reviewed extraction.
- Useful anomaly/forecast insights with uncertainty and backtested error.
- Grounded, citation-aware Q&A over bill documents and computed data.
- Strong ownership isolation and safe tool execution.

## Phase 1 MVP (no AI required)
1. Local CLI calculation for previous/current cumulative kWh and invalid-reading handling.
2. Browser UI later supports sign-in, property / meter management, reading entry and consumption history.
3. Basic dashboard shows computed kWh across intervals; excludes missing/invalid intervals.
4. Bill records manually entered and attached to the right property/meter and billing cycle.
5. Tests cover all domain calculations and basic authorization.

## Later increments
- Document upload, asynchronous extraction pipeline, field provenance, review-and-confirm UX.
- Tariff-aware calculations, effective-dated rule sets, estimate vs actual reconciliation.
- Statistical anomaly detection and time-series forecasting with walk-forward backtesting.
- LLM summaries grounded in computed facts, source quotations and uncertainty statements.
- RAG for uploaded bills, public utility explanation documents and user-authorized files.
- Agents/tools for read-only queries, then authorized draft actions; MCP server and client integration.
- Production telemetry, threat testing, deployment and portfolio presentation.

## Functional requirements
| ID | Requirement | Priority | Verification |
|---|---|---|---|
| FR-01 | Create and manage multiple properties per user | MVP-web | Owner-isolated API tests |
| FR-02 | Manage one or more meters per property with units and status | MVP-web | CRUD tests |
| FR-03 | Record cumulative meter reading, time, source and notes | MVP | Validation + test matrix |
| FR-04 | Compute validated interval kWh and date-normalized usage | MVP | Deterministic unit tests; kWh arithmetic is exact or fails explicitly |
| FR-05 | Reject/flag duplicates, reversals, reset and replacement events | MVP | Boundary tests |
| FR-06 | Browse history, charts and basic summary | MVP-web | UI/API integration tests |
| FR-07 | Create bill periods, billed kWh, amount and distributor | MVP-web | Domain/API tests |
| FR-08 | Compare billed kWh vs readings, explain mismatches | V2 | Reconciliation tests |
| FR-09 | Upload bill file with safe storage and validation | V3 | Malicious file tests |
| FR-10 | Extract fields with page/source provenance and human confirmation | V3 | Golden extraction evaluation |
| FR-11 | Version distributor tariffs and estimate costs | V4 | Tariff fixtures/regression |
| FR-12 | Detect anomalous periods with thresholds and baselines | V5 | Labeled anomaly cases |
| FR-13 | Forecast kWh with uncertainty and backtesting | V5 | Baseline comparison |
| FR-14 | Answer user questions from authorized data with citations | V6 | Grounding + authorization eval |
| FR-15 | Expose controlled tools, agent workflows and MCP server | V7 | Security/contract tests |
| FR-16 | Record audit, traces, model provenance and model evaluation | Cross-cutting | Observability tests |

## Non-functional requirements
- Security: password hashing through supported library; secure session or token strategy decided before auth implementation; ownership isolation in all queries.
- Resilience: no blocking dependency on AI provider for entering readings or viewing confirmed bills.
- Reliability: deterministic money/kWh math; explicit units; database constraints; idempotent upload/process operations.
- Performance goals (initial hypotheses): p95 read endpoints < 500 ms with modest seeded dataset and AI disabled; background extraction not on request thread. Benchmark locally, document hardware.
- Accessibility: keyboard-usable forms, labeled charts, readable errors, responsive interface.
- Privacy: local-first inference; redact PII from logs; configurable retention/deletion; use synthetic sample records.
- Maintainability: modular boundaries, versioned migrations, typed contracts, test gates, docs and ADRs.
- Portability: Docker Compose local setup; deployment guide with secrets and storage choices.

## Explicit exclusions
No utility meter hardware integration, payment collection, utility account credential scraping, automatic meter-reader OCR as ground truth, claiming to diagnose wiring faults, direct energy-grid control, automated refund or billing adjustments, multi-tenant enterprise roles, mobile native application, or microservices in the MVP.

## Success / portfolio acceptance
- Zero failed deterministic-domain test cases in checked-in suite.
- Demonstrated isolation: no user can read another user's property, bill, document or vector chunk.
- Bill extraction tested on at least 30 **synthetic or permitted anonymized** layouts; report per-field accuracy and correction rate (do not claim production readiness from a small sample).
- Forecast compared against naive seasonal baseline on time-separated test data; no invented performance target.
- RAG benchmark reports retrieval recall@k, citation support, unsupported-claim rate, and explicit abstention cases.
- Demo includes setup, synthetic seed data, example flows, architecture diagram, threat model and limitations.

## Risks and dependencies
- Real meter data may be sparse, irregular and not validated against distributor meters.
- Distributor invoices vary; OCR and local model vision capabilities must be benchmarked, not assumed.
- Tariffs change; retrieve official documentation and record effective dates before production estimates.
- Multi-meter totals are valid only across compatible intervals, meters and non-overlapping coverage.
- Local inference latency depends on laptop/desktop GPU and model; select after empirical benchmarks.
