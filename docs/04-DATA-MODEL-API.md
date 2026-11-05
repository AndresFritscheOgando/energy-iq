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
| `GET /health/ready` (unversioned, public) | 200 `{"status": "ready", "schema_revision": "<head>"}` when the database answers within 2 s and its Alembic revision is the code's head; else 503 | 2 (P2-02, built) |
| `POST /consumption/summary` | Stateless window summary over posted readings and events; stores nothing; needs a session and the CSRF header since P2-03 | 2 (P2-01, built) |
| `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | Accounts and server sessions in an HttpOnly cookie; login and register rate limited (429 with `Retry-After`) | 2 (P2-03, built) |
| `GET/POST /properties`, `GET/PATCH/DELETE /properties/{id}` | Owner scoped properties; DELETE archives (soft delete) | 2 (P2-03, built) |
| `GET/POST /properties/{id}/meters` (`include_inactive`), `GET/PATCH /meters/{id}`, `POST /meters/{id}/deactivate` | Meter management; deactivation is terminal, a replacement is a new meter | 2 (P2-03, built) |
| `POST/GET /meters/{id}/readings`, `PATCH /meters/{id}/readings/{reading_id}` | Store, list, flag, or void cumulative readings | 2 (P2-04, built) |
| `POST/GET /meters/{id}/events`, `POST /meters/{id}/events/{event_id}/approve`, `POST /meters/{id}/events/{event_id}/reject` | Record and decide meter events | 2 (P2-04, built) |
| `GET /meters/{id}/consumption?from=&to=` | Measured interval usage and coverage from stored data | 2 (P2-04, built) |
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
| 503 | `database_unavailable` | connection failure, pool checkout timeout, or statement timeout (`OperationalError`, pool `TimeoutError`); one warning line with the request id and the exception class only, never the DSN or SQL (P2-02) | |
| 503 | `schema_out_of_date` | readiness only: `alembic_version` is missing, empty, unreadable, or not the code's head (P2-02) | |
| 401 | `not_authenticated` | no valid session: missing, unknown, expired (14 days), idle (24 hours), revoked, or disabled user (P2-03). No `WWW-Authenticate` header: cookie sessions have no registered HTTP auth scheme, an accepted deviation from RFC 9110 | |
| 401 | `invalid_credentials` | login with an unknown email, wrong password, or disabled user; identical bodies apart from `request_id` (P2-03) | |
| 403 | `csrf_rejected` | `POST`, `PATCH`, or `DELETE` under `/api/v1` without `X-EnergyIQ-CSRF: 1`, or with an `Origin` that is `null`, foreign, and not in `ENERGYIQ_TRUSTED_ORIGINS` (P2-03) | |
| 404 | `not_found` | also a resource that does not exist, is archived, or belongs to someone else: the same body as an unknown path (P2-03) | |
| 409 | `email_taken` | registration email already exists (P2-03) | |
| 409 | `property_name_taken` | nickname in use among the owner's non archived properties, case insensitive (P2-03) | |
| 409 | `meter_label_taken` | label in use among the property's active meters, case insensitive (P2-03) | |
| 409 | `meter_inactive` | PATCH or deactivate on an inactive meter (P2-03) | |
| 400 | `invalid_idempotency_key` | `Idempotency-Key` is not 1 to 255 visible ASCII characters (P2-04) | |
| 409 | `idempotency_key_reused` | retry key belongs to another operation or body (P2-04) | |
| 409 | `reading_exists_at_instant` | non voided reading already exists at the UTC instant (P2-04) | `existing_reading_id` |
| 409 | `reading_voided` | change from a voided reading to another status (P2-04) | |
| 409 | `event_not_pending` | approve or reject an already decided event (P2-04) | |
| 429 | `too_many_attempts` | login: 5 failures for the email in 15 minutes since its last success, or 20 attempts from the client in 15 minutes; register: 5 attempts from the client in an hour. Header `Retry-After` in seconds (P2-03) | |

Checks run in a fixed order and the first failure answers: schema, duplicate ids, mapping, timestamp conflicts, computation. Validation `errors[].code` values come from a fixed catalog (`missing`, `unknown_field`, `invalid_type`, `invalid_uuid`, `invalid_kwh`, `invalid_datetime`, `datetime_out_of_range`, `invalid_enum`, `too_many_items`, `window_order`, `approval_pair`, `invalid_value`, `invalid_email`, `password_length`, `invalid_timezone`, `invalid_text_length`, `invalid_cursor`, `empty_patch`, `invalid_register_digits`, `reading_in_future`, `exactly_one_of`, `range_order`, `window_too_long`) and never echo the submitted value. For `unknown_field`, `loc` stops at the object that holds the key and omits the key itself, since the key is client text. The `validation_error` detail is `The request failed validation.` because query parameters validate too.

**Route check order (P2-03):** routing 404 or 405 → 413 → 403 `csrf_rejected` → 415 → 401 → 422 → 429 (login and register) → 404 ownership → 409 → write. FastAPI parses JSON before dependencies run, so a malformed body may answer 400 `malformed_json` ahead of 403 or 401.

**Sessions and CSRF (P2-03):** the cookie is `energyiq_session` (`__Host-energyiq_session` when `ENERGYIQ_SESSION_COOKIE_SECURE` is on), `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age=1209600`, no `Domain`. Only `sha256(token)` is stored. Login revokes a valid session cookie it was sent with. Attempts are keyed by `HMAC_SHA256(ENERGYIQ_SECRET_KEY, value)`; no raw email or IP is stored.

**Pagination (P2-03):** every list takes `limit` (1 to 500, default 100) and `cursor`, and answers `{"items": [...], "next_cursor": string | null}`. The cursor is opaque base64url; properties and meters sort by `(created_at, id)` ascending.

**Stored readings and events (P2-04):** `POST /meters/{id}/readings` accepts exactly one of an offset timestamp or a `local_date`. A date becomes noon in the property's IANA time zone, then UTC, and `original_local_date` retains the input. Future timestamps over five minutes ahead and future local dates are rejected. kWh response text has six fraction digits. A non voided reading at the same instant is a 409; a decrease is preserved and later shown as an invalid interval. Reading values and times are immutable; PATCH changes only status. Events start pending, then an owner approves or rejects once. Only non rejected events enter the stored summary. The summary loads the non voided readings in `[from, to)` plus the nearest one on each side; when that yields a single reading it also loads that reading's neighbor, so a window wholly before or after the history reports `before_first_reading` or `after_last_reading` rather than `no_intervals`. The whole read holds `FOR SHARE` on the property and meter rows, and every reading and event writer takes the meter update lock, so a concurrent correction cannot mix two committed states in one answer. It returns only overlapping intervals. All routes require the owner's session; POST and PATCH also require CSRF. The create and decide POSTs accept an optional `Idempotency-Key`, whose successful response bytes can be replayed for 24 hours without a second audit row.

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

`GET /api/v1/meters/{id}/readings` also accepts `order` of `asc` (default) or `desc`, which sorts by `(recorded_at, id)` descending and pages backward with the same cursor format. An unknown value is 422 `invalid_enum` (spec 0011 child 0001 AC-1).
