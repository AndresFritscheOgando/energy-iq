# 0012. Phase 4 bill intelligence

**Date**: 2026-11-05
**Status**: In Progress

## Summary

You can enter an invoice, keep its source, and compare its billed use with measured readings. An uploaded PDF can suggest fields, but you review and confirm every value. Cost estimates use only published, dated rules for a known tariff class. This spec covers P4-01 through P4-06.

## Structure

| Child | Ticket | Decision |
|---|---|---|
| [0001 Manual invoices](0001-manual-invoices.md) | P4-01 | Drafts, immutable revisions, confirmation, and source history |
| [0002 Private upload](0002-private-upload-jobs.md) | P4-02 | PDF upload, private storage, and recoverable processing runs |
| [0003 PDF text](0003-pdf-native-text.md) | P4-03 | Page text and an evidence based fallback evaluation |
| [0004 Ollama extraction](0004-ollama-extraction.md) | P4-04 | Bounded local proposals with a strict field contract |
| [0005 Review screens](0005-review-provenance-ui.md) | P4-05 | Human corrections and source evidence in the existing UI |
| [0006 Tariffs and comparison](0006-tariffs-reconciliation.md) | P4-06 | Official rule publication, narrow estimates, and honest kWh comparison |

## Requirements

**User stories**: US-005, US-006, and US-007 in `docs/06-USER-STORIES.md`.

**Acceptance criteria**:

- **AC-1**: A signed in owner can save an invoice draft for one owned meter. Confirmation requires distributor, start and end dates, billed kWh, and total DOP. The start cannot be after the end, so a one day period is valid. Issue date and due date may be absent. The source and author of each value remain visible.
- **AC-2**: Confirmed values are immutable. A correction creates a new revision with actor, time, changed fields, old values, and source. Two current confirmed invoices for one meter cannot have overlapping periods. Drafts may overlap.
- **AC-3**: An owner can upload a PDF to private storage. The system checks the file, caps resources, records its checksum, and returns a document and processing state. Retried upload and processing do not duplicate an invoice or lose the original.
- **AC-4**: Native PDF text extraction keeps page evidence. A scan without usable text goes to manual review. Local OCR or vision is enabled only after a recorded evaluation shows a benefit on permitted synthetic or anonymized layouts.
- **AC-5**: Ollama proposes typed fields with per field evidence and uncertainty. Schema, evidence, arithmetic, and domain checks run outside the model. Model failure leaves manual entry available and cannot alter a confirmed invoice.
- **AC-6**: The review screen displays the original source, proposed and corrected values, missing or conflicting fields, and provenance. Only an explicit owner action confirms a revision. Keyboard and screen reader use, loading, error, and retry states are verified.
- **AC-7**: Effective dated BTS-1 rules for EDESUR, EDEESTE, and EDENORTE can be published only from checked official SIE source material. A rule has its source, class, date range, version, and exact Decimal amounts. Unknown or ambiguous rules produce no cost estimate.
- **AC-8**: Reconciliation distinguishes billed kWh, measured kWh, coverage, energy charge estimate, and invoice total. A numeric kWh mismatch conclusion appears only with complete valid reading coverage. A cost estimate appears only when one applicable published rule covers the full invoice period and the invoice states BTS-1.
- **AC-9**: Owner isolation, CSRF, idempotency, audit, upload abuse, malicious document text, and model failures have negative tests. A versioned extraction corpus of at least 30 synthetic or permitted anonymized layouts reports field accuracy, missing and false field rates, correction rate, full document accuracy, latency, and local resource cost. No production accuracy claim is inferred from this corpus.

## Decision

**Chosen option**: Extend the existing FastAPI, PostgreSQL, and Next.js monolith in six vertical slices. Store source PDFs in a private local directory outside the web root. A bounded worker process claims database extraction runs; no new broker is required. Use native PDF text first, then a local Ollama adapter for proposals. Keep confirmed invoices and tariff calculations deterministic.

**Implementation skills**: `fastapi` (`.agents/skills/fastapi/`), `sqlalchemy-alembic-expert-best-practices-code-review` (`.agents/skills/sqlalchemy-alembic-expert-best-practices-code-review/`), `orval` (`.agents/skills/orval/`), `accessibility` (`.agents/skills/accessibility/`), `playwright-best-practices` (`.agents/skills/playwright-best-practices/`).

## Rationale

Reasoning and source links: see [rationale.md](rationale.md).

## Feature design

**Data model sketch**:

| Entity | Required fields | Optional fields and links | Relationship and constraint |
|---|---|---|---|
| `Invoice` | UUID, meter ID, owner ID, created UTC | current revision ID | One meter has many invoices. Owner comes from the meter property and is checked on every query. |
| `InvoiceRevision` | UUID, invoice ID, revision number, status, actor ID, created UTC, typed distributor, period dates, billed kWh, DOP total, field origins JSON | source document ID, previous revision ID, confirmed UTC, energy charge, issue date, due date | One invoice has many immutable revisions. Only one current revision. Confirmed revisions require the AC-1 fields. |
| `InvoiceCurrentPeriod` | invoice ID, meter ID, half open local date range | current revision ID | One row per current confirmed invoice. A database exclusion constraint prevents overlapping ranges for one meter. A correction replaces this row in the same transaction as the current pointer. |
| `SourceDocument` | UUID, owner ID, property ID, meter ID, opaque storage key, PDF MIME, byte count, SHA-256, state, created UTC | deleted UTC | One meter has many documents. Storage key is never returned to clients. |
| `ExtractionRun` | UUID, document ID, state, attempt count, created UTC | lease until UTC, started and finished UTC, model and prompt versions, proposed fields JSON, validation codes JSON, token count, elapsed time | One document has many runs. One active run per document. A run does not write a confirmed invoice. |
| `FieldEvidence` | run ID, field name, page number, exact text span, origin type | bounding box | Many evidence rows per run. The span must match retained page text or be explicitly marked as unverified. |
| `TariffSchedule` | UUID, distributor, class, effective dates, publication state, revision, source URL, source digest, checked UTC, checked by | published UTC | No overlapping published scope for the same distributor and class. Once published, rates and source are immutable. |
| `TariffBand` | schedule ID, ordered threshold, rate as Decimal, charge type | fixed charge as Decimal | Many bands per schedule. Rates and rounding rules must be copied from the source, never generated by a model. |

Do not store account numbers, customer names, or addresses in the invoice schema. Preserve an original PDF only when the owner uploads it. A manual invoice without a file records `manual` as each entered field's origin. All money uses exact DOP centavos or Decimal with an explicit source rounding rule.

**State transitions**: Invoice revision `draft` to `confirmed`; correction creates a new `draft` revision and confirmation makes it current in one transaction. The former confirmed revision remains history. Document `uploaded` to `processing` to `needs_review` or `failed`; `failed` can get a new run; owner deletion moves to `deleted`. A document never becomes a verified invoice on its own. Extraction run `queued` to `running` to `succeeded`, `needs_review`, or `failed`. Only a worker lease can be retried. Tariff `draft` to `published`; published rules are immutable and a replacement is a new revision.

**Cross child rules**:

- UI dates are local dates in the property's time zone, default `America/Santo_Domingo`. A billing period entered as inclusive local dates maps to a half open UTC window ending at midnight after the last date. The response displays the original dates.
- Existing consumption logic counts only valid measured intervals fully inside its requested window. Reconciliation must show its typed gaps and never allocate a partial interval as if it were observed daily use.
- Each read and write joins through the owned property and meter before loading a document, run, revision, or invoice. A foreign ID answers the same 404 as an unknown ID.
- Every mutation has CSRF and an audit row with IDs, state changes, and field names only. Use the existing `Idempotency-Key` contract on create, confirm, and retry operations.
- Parsed text and model proposals are untrusted data. They cannot supply owner IDs, choose a storage path, publish tariffs, invoke tools, or bypass validation.

**API surface**: The children define request and response fields. All paths start with `/api/v1`, use the existing session cookie, problem format, and pagination convention. Mutations require the existing CSRF header.

| Path | Method | Purpose |
|---|---|---|
| `/meters/{id}/invoices` | GET, POST | Paginated current invoices and manual draft creation |
| `/invoices/{id}` | GET | Current revision and history summary |
| `/invoices/{id}/revisions` | POST | Create corrected draft |
| `/invoices/{id}/confirm` | POST | Confirm one draft revision under a version check |
| `/meters/{id}/documents` | POST | Upload one PDF and queue extraction |
| `/documents/{id}`, `/documents/{id}/source` | GET | State and authorized source download |
| `/documents/{id}/retry`, `/documents/{id}` | POST, DELETE | Retry extraction or delete source and derived text |
| `/documents/{id}/extractions` | GET | Paginated proposals and evidence |
| `/meters/{id}/reconciliation` | GET | Invoice comparison and any supported tariff estimate |

**Value sourcing**:

| Action | Value displayed or produced | Source |
|---|---|---|
| Confirm invoice | distributor, dates, billed kWh, DOP total, field origins | Reviewed draft revision and its owner action |
| Correct invoice | old and new values, actor, time | Immutable revisions, session user, injected UTC clock |
| Show document | state, checksum, original PDF | Document row and private file, checked by owner |
| Show proposed field | value, missing or uncertain flag, page and text | Extraction run and `FieldEvidence`; absent evidence remains unverified |
| Compare kWh | measured kWh, coverage, gaps, billed kWh | Existing meter consumption service over the bill period and confirmed revision |
| Estimate energy charge | BTS-1 class, rates, dates, source, amount | Confirmed revision and one published matching SIE schedule with exact Decimal arithmetic |

**Security model**: These are private household documents. Session ownership checks and CSRF cover every route. PDF bytes are stored with an opaque server generated name outside public directories. Downloads require authorization and use attachment disposition with `nosniff`. Upload and worker limits cap bytes, pages, decoded content, run time, attempts, and concurrent runs. Do not log file bytes, extracted text, prompts, account details, or field values. Real personal data never enters tests or external models by default.

**Configuration required**: `ENERGYIQ_DOCUMENT_ROOT` names the private storage directory; the upload, page, text, CPU, wall clock, memory, attempt, run, concurrency, and per owner limits and their defaults are defined in [child 0002](0002-private-upload-jobs.md), along with `ENERGYIQ_WORKER_ISOLATION`; `ENERGYIQ_OLLAMA_URL`, `ENERGYIQ_OLLAMA_MODEL`, and `ENERGYIQ_OLLAMA_TIMEOUT_SECONDS` configure local inference. Validate and pin actual bounds and model digest during each build slice. An absent Ollama setting disables proposal processing but never manual entry.

**Critical test scenarios**: A synthetic PDF moves through upload, proposal, review, confirmation, correction, and comparison for AC-1 to AC-9. Cross owner IDs fail for every nested resource for AC-9. An invalid PDF, scan, parser timeout, stale lease, malformed JSON, unsupported value, prompt injection, conflicting evidence, overlapping period, absent tariff, and incomplete reading coverage exercise AC-2 to AC-9.

## Build plan

No project approach is recorded. Use a thin end to end thread through the current monolith, then widen it in ticket order. Phase 3 spec 0011 needs its fresh review before Phase 4 is treated as the current implementation phase.

1. Build child 0001 with its migration, API, and manual review form. Prove a confirmed synthetic invoice and a versioned correction through the browser, satisfies **AC-1**, **AC-2**, and the manual part of **AC-9**.
2. Build child 0002 with private storage, a document and run migration, and a bounded local worker. Prove upload, authorization, failure recovery, and deletion, satisfies **AC-3** and part of **AC-9**.
3. Build child 0003 with native text extraction and a versioned fallback evaluation. No OCR or vision implementation is required until its benchmark supports one, satisfies **AC-4** and part of **AC-9**.
4. Build child 0004 with the provider contract and fake adapter. Run the opt in local model benchmark separately, satisfies **AC-5** and part of **AC-9**.
5. Build child 0005 against `docs/screen-references/` with accessible source and correction views, satisfies **AC-6** and part of **AC-9**.
6. Build child 0006 using checked SIE documents, exact tariff fixtures, and reconciliation tests, satisfies **AC-7**, **AC-8**, and the final part of **AC-9**.
7. Update the roadmap, API and data model docs, AI evaluation report, README, ADRs where a significant choice changes, and `docs/PROGRESS.md`. Run the database, backend, frontend, browser, and opt in extraction checks appropriate to each slice, satisfies **AC-9**.

## Consequences

**Positive**:

- Every confirmed value can be traced to a person or source, and a failed model never blocks manual entry.
- The cost estimate cannot silently use an obsolete or invented rate.

**Negative / tradeoffs**:

- Private files need backup and deletion procedures. Database transactions cannot atomically commit filesystem writes, so the worker and deletion path need reconciliation checks.
- Strict full coverage makes many billed periods incomparable until readings align with the bill boundaries.
- BTS-1 only and a single applicable schedule deliberately leave many invoices without an estimate.

## Follow-up

- [ ] Resolve spec 0011's fresh review before Phase 4 implementation is marked current.
- [ ] During P4-03, record the native text and OCR or vision benchmark results before enabling any fallback. Native baseline recorded 2026-11-05 in `docs/evals/native-text-baseline.md`; the OCR or vision benchmark is still open.
- [ ] During P4-06, inspect the SIE resolution PDF itself and record its digest, exact tables, rounding, applicability, and fixture derivation before publishing a schedule.
- [ ] Before deployment, set and verify a private storage backup, owner deletion, and backup expiry policy. The owner may delete a source, but immutable audit metadata without private field values remains.
- [ ] Add the relevant installed implementation skill pointers to the proper context files through `/sync`.
