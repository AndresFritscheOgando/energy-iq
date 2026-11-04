# Domain Model and API Contracts (Specification, Not Code)

## Entities / important fields
- `User`: id UUID, email normalized/unique, password_hash or external subject, created_at, disabled_at.
- `Property`: id UUID, owner_user_id FK, nickname, optional region, timezone (`America/Santo_Domingo` default), timestamps.
- `Meter`: id UUID, property_id FK, utility_distributor enum/code (EDESUR/EDEESTE/EDENORTE/OTHER), meter_label, reading_unit `kWh`, installation/replacement metadata, active flag. From Phase 2, replacing a physical meter creates a new Meter record (the old one gets a final reading and becomes inactive; the new one gets an approved `installed` event and a first reading); see [ADR-006](adr/ADR-006-meter-replacement-new-record.md). A register digit count, needed for rollover kWh, is designed in Phase 2. How readings, events, and discontinuities behave for a meter is defined in the [meter semantics reference](12-METER-SEMANTICS.md).
- `MeterEvent`: id, meter_id, event_type (`installed`, `reset`, `replaced`, `rollover`, `calibration`), effective_at, approved metadata; separates discontinuities.
- `Reading`: id, meter_id, recorded_at UTC, original_local_date if manually entered, cumulative_kwh `Decimal`, source (`manual`, `import`), status (`valid`, `flagged`, `voided`), created_at, source_ref/idempotency_key.
- The P1-01 in-memory `Reading` model uses UUID ids, explicit aware zero-offset datetimes, and finite nonnegative Decimal kWh up to `999999999999.999999` with at most six meaningful fractional places. It never rounds. `original_local_date` is optional provenance, not a substitute for `recorded_at`. See [spec 0002](specs/0002-reading-meter-event-models.md).
- The P1-01 in-memory `MeterEvent` model records its kind, UTC effective and creation instants, and optional approval actor and instant as a pair. P1-03 applies its interval boundary rules.
- The P1-02 in-memory `order_readings` operation returns every reading in stable UTC timestamp order and all duplicate timestamp groups for one meter. Conflict entries retain original input positions and all statuses. Invalid items and mixed meter inputs fail with indexed errors. Conflicts require explicit resolution before interval computation. See [spec 0003](specs/0003-reading-order-conflicts.md).
- The P1-03 in-memory `ConsumptionInterval` is a derived immutable record with meter and endpoint reading IDs, UTC start and end, valid or invalid status, event IDs, optional exact Decimal kWh, and an invalid reason. `compute_intervals` rejects timestamp conflicts and malformed order, excludes voided readings, treats flagged readings as barriers, and returns no numeric result across events or unexplained decreases. An event at the current reading time starts the new segment. Unapproved, rollover, and calibration events block the affected pair. No interval is stored or materialized. See [spec 0004](specs/0004-reading-interval-boundaries/index.md).
- The P1-04 in-memory `normalize_intervals` gives each interval its real `duration` and, for valid intervals, `kwh_per_day` from exact elapsed microseconds (one day is 86,400 UTC seconds), rounded once half even to 6 places. `summarize_consumption` reports, for one meter and a half open UTC window, the exact `measured_kwh` of valid intervals fully inside the window, `covered` and `uncovered` durations, a `coverage_ratio` rounded once to 4 places, an average rate over covered time (or `None`), and one typed gap per uncovered span (`before_first_reading`, `after_last_reading`, `no_intervals`, `partial_interval`, `invalid_interval`). Measured intervals and gaps tile the window exactly. Nothing is estimated, and both functions require the complete touching `compute_intervals` chain for one meter. See [spec 0005](specs/0005-time-normalized-consumption-coverage/index.md).
- `Bill`: id, property_id, meter_id nullable only when legitimately unassigned, distributor, period_start/end (dates), billed_kwh nullable, total_due_money, currency DOP, issue_date, due_date, confirmation_status, source_document_id, breakdown/adjustments.
- `TariffSchedule`: id, distributor, customer_class, effective_from/to, source_url, published_at, revision, active_status, tariff rules stored as validated data; separate **energy charge** and other bill components.
- `Document`: id, owner_user_id, property_id, storage_key, mime, size, content_hash, state (`uploaded`, `processing`, `needs_review`, `confirmed`, `failed`, `deleted`), retention, created_at.
- `ExtractionRun`: id, document_id, model/tag/prompt version, proposed_fields JSON, validation_errors, field_evidence (page/region/text), run_duration, confirmation_user_id/time.
- `DocumentChunk`: id, document_id, chunk text/location metadata, embedding vector (phase 6), embedding_model/version; owner scope via joins/validated security boundary.
- `ForecastRun`: id, meter_id, training cutoff, horizon, method/version, predictions, intervals, metrics, status.
- `Anomaly`: id, meter_id, interval, score, baseline method, explanation/evidence, review status.
- `AgentRun` / `ToolInvocation`: user, scope, prompt/model/version, tool, arguments hash/redacted, authorization, outcome, approval, trace ID, timestamps.
- `AuditEvent`: actor id, action, entity, entity id, timestamp, redacted metadata.

## Invariants
1. Reading values >= 0, valid decimal scale. Readings within one stable meter segment must not decrease. A decrease requires a documented meter event and recomputation; don't simply discard.
2. UTC timestamps for event storage and interval calculations; user-facing dates in property timezone. Equal timestamps for same meter must be rejected or explicitly reconciled.
3. Consumption = next cumulative reading - previous, only within a compatible segment. Time-normalize for daily rates by actual elapsed interval, not by assuming each pair is 24 hours apart. Discontinuity rules, their precedence, and worked examples are in [meter semantics](12-METER-SEMANTICS.md).
4. Bills are not meter readings. Billed periods may not match observation windows; reconciliation shows coverage and limitations.
5. No overlapping active intervals for the same tariff rule scope; rates only applied to appropriate effective dates and customer category. Tariff complexity is domain-specific; require authoritative tariff fixtures before coding.
6. Money stored as `Decimal` or integer centavos, currency included; rounding declared and tested.
7. One user's ownership must be enforced for every property, meter, reading, bill, document, chunk, report and tool operation.
8. Confirmed extracted fields retain provenance and correction audit trail.
9. Missing readings are not fabricated. Forecasts are predicted values with method, intervals and uncertainty, never actuals.

## Conceptual REST surface (version prefix `/api/v1`)

The implemented Phase 0 calculation boundary requires finite nonnegative Decimal
inputs and returns an exact difference within a local precision 28 arithmetic
policy, or raises a Decimal arithmetic exception. It rejects unsupported runtime
types and does not coerce whole numbers, floats, or strings. This computation
policy is independent of future reading storage scale and physical range rules.
Elapsed time and sorting require datetime timestamps with zero UTC offsets.
These are local function contracts, not HTTP endpoints. P2-01 maps them to HTTP
([spec 0008](specs/0008-minimal-fastapi-application/index.md)); see HTTP error semantics below. See [Task 001](tasks/TASK-001-consumption-foundations.md).

| Method/path | Purpose | Phase |
|---|---|---|
| `GET /health` (unversioned) | Liveness and version, no dependencies | 2 (P2-01, built) |
| `POST /consumption/summary` | Stateless window summary over posted readings and events; stores nothing, no auth yet | 2 (P2-01, built) |
| `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | Auth/session | 2 |
| `GET/POST /properties`, `GET/PATCH/DELETE /properties/{id}` | Owner-scoped properties | 2 |
| `GET/POST /properties/{id}/meters` | Meter management | 2 |
| `POST /meters/{id}/readings`, `GET /meters/{id}/readings` | Record/list observations | 1/2 |
| `GET /meters/{id}/consumption?from=&to=` | Verified interval usage, coverage | 2 |
| `POST/GET /meters/{id}/bills` | Manual and confirmed bills | 3 |
| `POST /documents`, `GET /documents/{id}/status` | Upload + progress | 4 |
| `POST /documents/{id}/confirm` | Human-reviewed bill extraction | 4 |
| `GET /meters/{id}/reconciliation` | Bill/readings comparison | 4 |
| `GET /meters/{id}/forecast`, `GET /meters/{id}/anomalies` | Analytics | 5 |
| `POST /ai/questions` | Evidence-grounded question | 6 |
| `POST /agent/runs` | Authorized bounded workflow | 7 |

## API contract expectations
- Pydantic request/response models distinct from ORM. Never expose password hashes, storage keys or raw model prompts.
- Clear 400/401/403/404/409/422/429/503 semantics; consider not disclosing resource existence across tenants.
- Pagination, UTC ISO timestamps, decimal serialization policy, correlation IDs, idempotency for uploads and jobs.
- Rate limits and payload limits on all write/AI endpoints.
- Document OpenAPI and maintain sample request/response fixtures alongside endpoint implementation and contract tests.

## HTTP conventions and error semantics (P2-01, implemented)

Set by [spec 0008](specs/0008-minimal-fastapi-application/index.md); every later endpoint reuses them.

- **Values.** kWh, rates, and ratios are JSON strings: input matches `^[0-9]{1,12}(\.[0-9]{1,6})?$`, output is `format(value, "f")` of the exact Decimal. Input timestamps are JSON strings with an explicit offset, converted to UTC. Output timestamps are `YYYY-MM-DDTHH:MM:SS[.ffffff]Z`. Durations are ISO 8601 (`P1DT2H30M`, `PT0S`). Nullable fields are always present.
- **Server owned fields.** `created_at` is stamped by the server from one injected clock instant per request; clients cannot send it. Unknown fields are rejected everywhere.
- **Errors.** Every non 2xx response is `application/problem+json` (RFC 9457): `type` (`about:blank`), `title` (reason phrase), `status`, `detail` (fixed per code), `code`, `request_id`. Clients branch on `code`, never on `detail`. Two exceptions are answered before the app runs: Starlette's plain 400 for a rejected CORS preflight, and uvicorn's plain 400 for a request its HTTP parser rejects (for example a non integer `Content-Length`).
- **Tracing.** Every response carries `X-Request-ID` (a valid client value `^[A-Za-z0-9-]{1,64}$` is echoed, else a new UUID4). Each request writes one JSON access line (`timestamp`, `level`, `request_id`, `method`, `route`, `status`, `duration_ms`) on `energyiq.access`; no body, query, header value, or client address is logged.
- **Limits.** Bodies over `ENERGYIQ_MAX_BODY_BYTES` (default 1 MiB) are rejected, declared or streamed. Lists are capped at 5,000 readings and 500 events.

| Status | `code` | When | Extension member |
|---|---|---|---|
| 400 | `malformed_json` | unparseable JSON, invalid UTF-8, or empty body on a JSON route | |
| 400 | `invalid_content_length` | `Content-Length` is not a non negative integer and the request reaches the app (defense in depth; uvicorn's parser normally rejects it first with a plain 400) | |
| 404 | `not_found` | no route matches | |
| 405 | `method_not_allowed` | route exists, method does not (`Allow` header kept) | |
| 413 | `payload_too_large` | body over the byte cap | |
| 415 | `unsupported_media_type` | JSON route without `application/json` (only `charset=utf-8` allowed) | |
| 422 | `validation_error` | schema or field rule failed | `errors[]` of `{loc, code, message}`, first 100, plus `errors_truncated` |
| 422 | `duplicate_id` | repeated id within readings or within events | `duplicates[]` of `{collection, id, input_indexes}` |
| 422 | `reading_timestamp_conflict` | readings share a UTC instant (all statuses) | `conflicts[]` of `{recorded_at, entries[{input_index, reading_id, status}]}` |
| other | `http_<status>` | any other `HTTPException` | |
| 500 | `internal_error` | anything unexpected; generic detail, traceback logged once with the request id | |

Checks run in a fixed order and the first failure answers: schema, duplicate ids, mapping, timestamp conflicts, computation. Validation `errors[].code` values come from a fixed catalog (`missing`, `unknown_field`, `invalid_type`, `invalid_uuid`, `invalid_kwh`, `invalid_datetime`, `datetime_out_of_range`, `invalid_enum`, `too_many_items`, `window_order`, `approval_pair`, `invalid_value`) and never echo the submitted value. 409 is reserved for stored state conflicts (P2-04); 401, 403, and 429 arrive with P2-03.

## Model of one reading (illustrative schema only)
```json
{
  "meter_id": "<uuid>",
  "recorded_at": "2026-10-25T12:00:00-04:00",
  "cumulative_kwh": "13049.0",
  "source": "manual"
}
```
Use synthetic examples; never put real meter/account identifiers in tests.
