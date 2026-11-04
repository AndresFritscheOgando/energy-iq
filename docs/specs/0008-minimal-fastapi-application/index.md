# 0008. Minimal FastAPI application with problem details errors

**Date**: 2026-11-03
**Status**: In Progress

## Summary

This spec covers P2-01, the first HTTP surface of EnergyIQ. It adds a small FastAPI app with a health check and one stateless endpoint. You send it readings, meter events, and a time window, and it returns the Phase 1 consumption summary and intervals. Nothing is stored, and there is no login yet (P2-02 adds the database, P2-03 adds auth). The point is to fix the HTTP contract early: exact decimal strings, UTC timestamps, one standard error shape (RFC 9457 problem details, a JSON error format), request ids, and size limits, so later endpoints reuse them instead of inventing their own.

## Requirements

**User stories**:
- As the future Next.js client (P3), I want one predictable JSON contract for values and errors, so every screen handles success and failure the same way.
- As a developer, I want to post synthetic readings and see the exact Phase 1 summary over HTTP, so the domain is proven through the real server before persistence arrives.
- As an operator, I want every request traceable by a request id and bounded in size, so failures are diagnosable and one request cannot exhaust the process.

**Acceptance criteria**:
- **AC-1**: `energyiq.main.create_app(settings: Settings | None = None) -> FastAPI` builds the app. The documented command `uv run uvicorn energyiq.main:create_app --factory --app-dir backend/src --no-access-log` starts a working server. `GET /health` returns 200 `{"status": "ok", "version": "0.1.0"}`; `version` is `energyiq.__version__`, which a test proves equals `[project].version` in `pyproject.toml`. Health makes no database or network call.
- **AC-2**: `POST /api/v1/consumption/summary` with a valid body returns 200 `application/json`. Its numbers, statuses, reasons, and ids equal the result of running `order_readings` → `compute_intervals` → `normalize_intervals` and `summarize_consumption` on the same mapped domain records. The body contains `meter_id`, `window {start, end}`, `measured_kwh`, `covered`, `uncovered`, `coverage_ratio`, `average_kwh_per_day`, `gaps[]`, and `intervals[]` (every interval in the chain, in time order, each with `measured_in_window`).
- **AC-3**: Output serialization, by the API's own serializers (not library defaults). Every Decimal (`measured_kwh`, `coverage_ratio`, `average_kwh_per_day`, `consumption_kwh`, `kwh_per_day`) is a JSON string produced by `format(value, "f")` of the exact domain value, typed `string` in OpenAPI: never a JSON number, never exponent form (the domain can produce `Decimal("0E-8")`, which must print `"0.00000000"`). Every datetime is `YYYY-MM-DDTHH:MM:SSZ`, or `YYYY-MM-DDTHH:MM:SS.ffffffZ` when microseconds are nonzero (always six fraction digits then). Every duration (`covered`, `uncovered`, gap and interval `duration`) is ISO 8601 `P[nD]T[nH][nM][n[.f]S]`: zero components omitted, the fraction trimmed of trailing zeros, zero duration `PT0S` (examples: `P1DT2H30M`, `PT0.000001S`, `P3D`). Nullable fields are always present, as `null` when empty. Enum values are the domain strings.
- **AC-4**: Input validation returns 422 `validation_error` with `errors[]` items located by path (for example `["body", "readings", 3, "cumulative_kwh"]`) for: `cumulative_kwh` that is not a JSON string, or does not match `^[0-9]{1,12}(\.[0-9]{1,6})?$` (sign, exponent, `NaN`, blank, a 13th integer digit, a 7th fraction digit including trailing zeros, and JSON numbers all fail); a datetime that is not a JSON string (JSON numbers fail), has no offset, or overflows on UTC conversion (for example `9999-12-31T23:00:00-04:00`); `window.end <= window.start`; an unknown field anywhere in the body; more than 5,000 readings or more than 500 events; an `approved_by` without `approved_at`, or the reverse. Datetimes with `Z` or any explicit offset (for example `-04:00`) are accepted and converted to UTC before the domain sees them. Input with no computable interval (empty `readings`, a single reading, or only voided readings) is valid and returns 200 with `measured_kwh` `"0"`, `coverage_ratio` `"0.0000"`, `average_kwh_per_day` `null`, and one `no_intervals` gap covering the window.
- **AC-5**: Server owned values: a request body containing `created_at` fails with 422 (unknown field). The server stamps one request instant, UTC, from an injectable clock, as `created_at` on every mapped reading and event. Reading `status` defaults to `valid` and `source` to `manual` when omitted. Every domain validation rule is enforced in the request schemas, so building domain records from a validated request never raises; any exception from mapping or computation is a bug and returns 500 (AC-8).
- **AC-5a**: Checks run in this fixed order, and the first failing stage answers: (1) schema validation → 422 `validation_error`; (2) duplicate ids → 422 `duplicate_id`; (3) mapping to domain records; (4) `order_readings` conflicts → 422 `reading_timestamp_conflict`; (5) compute and respond. A request with both duplicate ids and timestamp collisions returns `duplicate_id`.
- **AC-6**: Two readings with the same `id`, or two events with the same `id`, return 422 `duplicate_id` with `duplicates: [{"collection": "readings" | "events", "id", "input_indexes": [...]}]` listing every repeated id. A reading and an event may share an id (they are separate collections). The domain is not called.
- **AC-7**: Readings at the same UTC instant return 422 `reading_timestamp_conflict` with `conflicts: [{"recorded_at", "entries": [{"input_index", "reading_id", "status"}]}]` holding every P1-02 conflict group, across all statuses including `voided`, with no summary computed.
- **AC-8**: Every non 2xx response, from a route or from middleware, has `Content-Type: application/problem+json` and the body `{"type": "about:blank", "title", "status", "detail", "code", "request_id"}`, plus the extension member named in AC-4, AC-6, or AC-7 where it applies. There are two documented exceptions, both answered before the app runs: a rejected CORS preflight (AC-11), and a request the server's HTTP parser rejects as malformed (for example a non integer `Content-Length`), which uvicorn answers with its own plain text 400 and no `X-Request-ID`. `title` is the HTTP reason phrase; `detail` is the fixed string for the code in the error catalog. Validation `errors[]` items are `{"loc", "code", "message"}` with `code` and `message` from the API's validation catalog (never Pydantic's `msg`, which can quote input), never echo the submitted value, and are capped at the first 100 (`errors_truncated: true` when cut). Unparseable JSON, a body that is not valid UTF-8, and an empty body on a JSON route return 400 `malformed_json`. When a non integer `Content-Length` does reach the app (a server that passes the header through, or a direct ASGI call), it returns 400 `invalid_content_length`; this check is defense in depth, since uvicorn's parser normally rejects such a request first. An unknown path returns 404 `not_found`. A wrong method returns 405 `method_not_allowed` with the `Allow` header preserved. Any other `HTTPException` status maps to code `http_<status>`. An unhandled exception returns 500 `internal_error` with a generic `detail`, no exception text or traceback, and exactly one server log entry carrying the `request_id` and the traceback; if the response had already started, the connection is closed and nothing more is sent.
- **AC-9**: On a matched route that takes a JSON body, a request whose `Content-Type` is missing or is not `application/json` (only the parameter `charset=utf-8` allowed) returns 415 `unsupported_media_type`. An unmatched path or method still returns 404 or 405 first (for example `POST /health` without JSON is 405, `POST /nope` is 404). A body larger than `ENERGYIQ_MAX_BODY_BYTES` (default 1,048,576) returns 413 `payload_too_large`, both when `Content-Length` declares it (rejected before reading) and when a chunked body without a length grows past the cap (rejected as soon as the running count exceeds it, never surfacing as 400).
- **AC-10**: Every response the app produces, including 413, 415, and 500, carries `X-Request-ID` (requests the server's HTTP parser rejects never reach the app; see AC-8). A client value matching `^[A-Za-z0-9-]{1,64}$` is echoed; anything else is replaced by a new UUID4. Problem bodies carry the same value in `request_id`. Each request writes exactly one JSON log line on logger `energyiq.access` with `timestamp` (UTC), `level`, `request_id`, `method`, `route`, `status`, and `duration_ms`, and no other keys. `route` is the matched route template from `scope["route"]`, else `"unmatched"` (this includes 413 rejected before routing and the docs routes). On client disconnect before a response, `status` is `499`. No body, query string, header value, or client address is logged. Calling `create_app` repeatedly never duplicates log handlers.
- **AC-11**: `Settings` reads `ENERGYIQ_*` environment variables, and an invalid value (for example `ENERGYIQ_ENV=staging`) fails `create_app` with a validation error naming the field. With `env=prod`, `/docs`, `/redoc`, and `/openapi.json` return 404; with `dev` or `test` they are served. When `ENERGYIQ_CORS_ORIGINS` is non empty (default `["http://localhost:3000"]` for `dev` and `test`, `[]` for `prod`), Starlette `CORSMiddleware` allows those origins with methods `GET` and `POST`, request headers `Content-Type` and `X-Request-ID`, and `X-Request-ID` exposed; when it is empty, no CORS middleware is installed. `Access-Control-Allow-Credentials` is never sent. A disallowed origin never receives `Access-Control-Allow-Origin`; its preflight gets Starlette's plain 400 (the documented exception to AC-8). A 500 carries no CORS headers.
- **AC-12**: The OpenAPI document describes the request and response models and, on the summary route, the Problem schema for 400, 413, 415, 422, and 500 under `application/problem+json` only (an `openapi` override removes the `application/json` entry FastAPI generates). Declaring `422` in the route's `responses` removes the default `HTTPValidationError` and `ValidationError` components, and a test asserts they are absent. The document equals the committed snapshot `backend/tests/snapshots/openapi.json`. Importing `energyiq.readings` in a fresh interpreter leaves `fastapi`, `starlette`, and `pydantic` out of `sys.modules` (a subprocess test asserts it, which covers transitive imports).
- **AC-13**: A live smoke test starts the documented uvicorn command as a subprocess on a free port, calls `/health` and one summary request with httpx, and stops it. The full suite, Ruff lint and format, and Pyright pass. New dependencies are pinned in `pyproject.toml` and `uv.lock`. README documents the run command; `docs/04-DATA-MODEL-API.md` records the error semantics table.

## Decision

**Chosen option**: Option 2: Health check plus one stateless consumption summary endpoint

Build a FastAPI app factory with `GET /health` and `POST /api/v1/consumption/summary`, wrapping the unchanged Phase 1 domain, with RFC 9457 problem details for every error, decimal strings, UTC timestamps, request ids, body caps, settings, and CORS fixed as the project's HTTP conventions.

**Implementation skills**: none installed for this stack (see Follow-up).

## Rationale

Reasoning, options, and the sub decisions with their runners up: see [rationale.md](rationale.md).

## Feature design

**Data model sketch**: no persistence (P2-02 owns the schema). The contract is these request and response models (Pydantic, all request models `extra="forbid"`, all frozen):

| Model | Fields |
|---|---|
| `ConsumptionSummaryRequest` | `meter_id: UUID` (req) · `window: WindowIn` (req) · `readings: list[ReadingIn]` (req, 0 to 5,000) · `events: list[EventIn]` (opt, default `[]`, 0 to 500) |
| `WindowIn` | `start: UtcInstant` (req) · `end: UtcInstant` (req, after `start`) |
| `ReadingIn` | `id: UUID` (req) · `recorded_at: UtcInstant` (req) · `cumulative_kwh: KwhString` (req) · `status: ReadingStatus` (opt, `valid`) · `source: ReadingSource` (opt, `manual`) |
| `EventIn` | `id: UUID` (req) · `event_type: MeterEventType` (req) · `effective_at: UtcInstant` (req) · `approved_by: UUID \| None` · `approved_at: UtcInstant \| None` (both or neither) |
| `ConsumptionSummaryResponse` | `meter_id` · `window {start, end}` · `measured_kwh` · `covered` · `uncovered` · `coverage_ratio` · `average_kwh_per_day \| null` · `gaps: list[GapOut]` · `intervals: list[IntervalOut]` |
| `GapOut` | `start` · `end` · `duration` · `reason: GapReason` · `interval_reason \| null` · `previous_reading_id \| null` · `current_reading_id \| null` · `event_ids: list[UUID]` |
| `IntervalOut` | `previous_reading_id` · `current_reading_id` · `start` · `end` · `duration` · `status: IntervalStatus` · `reason \| null` · `event_ids` · `consumption_kwh \| null` · `kwh_per_day \| null` · `measured_in_window: bool` |
| `HealthResponse` | `status: Literal["ok"]` · `version: str` |
| `Problem` | `type` · `title` · `status: int` · `detail` · `code` · `request_id` · optional `errors`, `duplicates`, `conflicts` |

Shared types: `KwhString = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,12}(\.[0-9]{1,6})?$")]`, converted to `Decimal` in mapping (lax `str` already rejects JSON numbers; do not build it on `Decimal`, whose strict mode still accepts numbers). `UtcInstant = Annotated[AwareDatetime, Field(strict=True)]` plus an after validator that converts to UTC and turns `OverflowError` into `datetime_out_of_range`. Response Decimal fields are typed `str` and durations and datetimes are rendered by the API's own formatters (AC-3), so OpenAPI shows them as strings.

Not accepted from clients: `created_at`, `note`, `source_ref`, `original_local_date` (the date only conversion belongs to P2-04), and per reading or per event `meter_id` (all records belong to the top level `meter_id`, so mixed meter input cannot occur).

**State transitions**: none.

**API surface**:
| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/health` | GET | none | `status`, `version` | public | 404/405 only |
| `/api/v1/consumption/summary` | POST | `meter_id`, `window`, `readings[]`, `events[]` (JSON) | summary + `gaps[]` + `intervals[]` | public (no auth until P2-03) | 400 `malformed_json` / `invalid_content_length`, 413 `payload_too_large`, 415 `unsupported_media_type`, 422 `validation_error` / `duplicate_id` / `reading_timestamp_conflict`, 500 `internal_error` |
| `/docs`, `/redoc`, `/openapi.json` | GET | none | docs | public, off in `prod` | 404 in `prod` |

**Error code catalog** (the `code` member; clients branch on it, never on `detail`; `detail` is the fixed string below):
| Status | `code` | When | `detail` |
|---|---|---|---|
| 400 | `malformed_json` | unparseable JSON, invalid UTF-8, or empty body on a JSON route | `The request body is not valid JSON.` |
| 400 | `invalid_content_length` | `Content-Length` is not a non negative integer and the request reaches the app (uvicorn's parser normally answers first with a plain 400) | `The Content-Length header is invalid.` |
| 404 | `not_found` | no route matches | `No resource exists at this path.` |
| 405 | `method_not_allowed` | route exists, method does not | `This method is not allowed for this path.` |
| 413 | `payload_too_large` | body over the byte cap | `The request body exceeds the size limit.` |
| 415 | `unsupported_media_type` | JSON route without `application/json` | `The request body must be application/json.` |
| 422 | `validation_error` | schema or field rule failed (`errors[]`) | `The request body failed validation.` |
| 422 | `duplicate_id` | repeated id in one collection (`duplicates[]`) | `Ids must be unique within readings and within events.` |
| 422 | `reading_timestamp_conflict` | P1-02 conflict groups (`conflicts[]`) | `Readings share a timestamp and must be resolved first.` |
| any other | `http_<status>` | another `HTTPException` | the reason phrase |
| 500 | `internal_error` | anything unexpected | `An unexpected error occurred.` |

**Validation catalog** (`errors[].code` → `message`; Pydantic error types map to these, anything unmapped becomes `invalid_value`):
| `code` | `message` |
|---|---|
| `missing` | `Field is required.` |
| `unknown_field` | `Field is not allowed.` |
| `invalid_type` | `Value has the wrong JSON type.` |
| `invalid_uuid` | `Value must be a UUID string.` |
| `invalid_kwh` | `Value must be a decimal string with at most 12 integer and 6 fraction digits.` |
| `invalid_datetime` | `Value must be an ISO 8601 string with an explicit offset.` |
| `datetime_out_of_range` | `Value is outside the supported datetime range.` |
| `invalid_enum` | `Value is not one of the allowed options.` |
| `too_many_items` | `List exceeds its maximum length.` |
| `window_order` | `window.end must be after window.start.` |
| `approval_pair` | `approved_by and approved_at must be given together.` |
| `invalid_value` | `Value is invalid.` |

409 is reserved for stored state conflicts (duplicates, idempotency) from P2-04. 401, 403, and 429 arrive with P2-03.

**Value sourcing**:
| Action | Value produced / displayed | Source |
|---|---|---|
| health | `version` | `energyiq.__version__` constant, tested against `pyproject.toml` |
| summary | domain `Reading.id`, `recorded_at`, `cumulative_kwh`, `status`, `source` | request `readings[i]` (UTC converted; defaults `valid`, `manual`) |
| summary | domain `Reading.meter_id`, `MeterEvent.meter_id` | request top level `meter_id` |
| summary | domain `created_at` (readings and events) | injected clock, one UTC instant per request (`platform.clock.get_now` dependency) |
| summary | domain `MeterEvent` fields | request `events[i]` |
| summary | window bounds | request `window`, converted to UTC |
| summary | `measured_kwh`, `covered`, `uncovered`, `coverage_ratio`, `average_kwh_per_day`, `gaps` | `summarize_consumption` (spec 0005) |
| summary | interval fields, `kwh_per_day` | `normalize_intervals(compute_intervals(...))` (specs 0004, 0005) |
| summary | `measured_in_window` | derived: the interval is `valid` and lies fully inside `[window.start, window.end)` (the same rule `summarize_consumption` uses for `measured_intervals`) |
| summary | Decimal string text | `format(value, "f")` of the exact domain Decimal (no rounding added at the API) |
| summary | datetime and duration text | API formatters `format_utc` and `format_duration` in `platform/http/formats.py` (AC-3) |
| every problem | `detail` | fixed string per `code`, error catalog |
| `validation_error` | `errors[].code`, `message`, `loc` | Pydantic error `type` mapped through the validation catalog; `loc` from Pydantic; first 100 kept |
| `duplicate_id` | `duplicates[]` | derived from request ids and their input indexes |
| `reading_timestamp_conflict` | `conflicts[]` | `ReadingOrderResult.conflicts` (spec 0003), `input_index` from the domain entry |
| every response | `X-Request-ID`, `request_id` | valid client header, else `uuid4()` |
| every problem | `title` | HTTP reason phrase for `status` |
| access log | `route` | matched route template from the ASGI scope, else `"unmatched"` |
| access log | `duration_ms` | `time.perf_counter()` around the request, rounded to 3 places |

**Module layout**:
- `energyiq/__init__.py`: add `__version__ = "0.1.0"`.
- `energyiq/main.py`: `create_app`, middleware order, router registration, docs toggle.
- `energyiq/platform/settings.py`: `Settings(BaseSettings)`, `env_prefix="ENERGYIQ_"`.
- `energyiq/platform/clock.py`: `get_now() -> datetime` (aware UTC), overridable through `app.dependency_overrides`.
- `energyiq/platform/http/problems.py`: `Problem` model, `ProblemError` exception, `problem_response()` renderer, the two catalogs, handlers for `RequestValidationError` and Starlette `HTTPException` (copying `exc.headers`).
- `energyiq/platform/http/formats.py`: `format_decimal`, `format_utc`, `format_duration`.
- `energyiq/platform/http/middleware.py`: pure ASGI `RequestContextMiddleware` and `BodySizeLimitMiddleware`.
- `energyiq/platform/http/dependencies.py`: `require_json` dependency (415), attached to every route that takes a JSON body.
- `energyiq/platform/logging.py`: `configure_logging(level)`, idempotent (installs the JSON formatter handler on `energyiq.access` and `energyiq` once per process).
- `energyiq/platform/http/health.py`: health router.
- `energyiq/readings/api/schemas.py`, `mapping.py` (DTO to domain and back, duplicate and conflict checks), `router.py`.

Middleware order, outermost first: `RequestContextMiddleware` → `CORSMiddleware` (only when origins are configured) → `BodySizeLimitMiddleware` → routes.
- `RequestContextMiddleware` sets the request id in `scope["state"]["request_id"]`, adds `X-Request-ID` to every response start message, and catches every exception itself: it logs the traceback once with the request id, sends the 500 problem if the response has not started, and does not re raise. No `Exception` handler is registered on the app (Starlette would run it outside all middleware, without the request id).
- `BodySizeLimitMiddleware` returns 400 `invalid_content_length` or 413 directly through `problem_response()` when `Content-Length` decides it. For streamed bodies its `receive` wrapper raises Starlette `HTTPException(413)` once the count passes the cap, which FastAPI re raises instead of wrapping as 400.
- The summary route declares `responses` for 400, 413, 415, 422, 500 with the `Problem` model; `create_app` overrides `app.openapi` to move those entries to `application/problem+json` only.

**Key invariants**:
- No binary float touches a kWh, rate, or ratio value on input or output.
- The domain receives only zero offset UTC datetimes; the API owns the offset conversion.
- The domain package stays framework free (AC-12); API models are separate from domain dataclasses.
- The request schemas enforce every rule the domain checks (kWh digits and range, UTC, approval pair, window order), so mapping never raises on validated input. Any domain exception after schema validation, including a `decimal.DecimalException`, is a bug and surfaces as 500, never as 422 or a silent 200. The 12 integer and 6 fraction digit cap also keeps a 5,000 reading sum inside the domain's precision 28 context.
- Route handlers are sync `def` (pure CPU work runs in the threadpool, never on the event loop).

**Security model**: no authentication or ownership in P2-01; the endpoint stores nothing, reads nothing server side, and holds no user data, so there is nothing to scope yet. Event approval fields are client stated inputs to a calculation, not an authorization decision; persisted approvals with a recorded actor come with P2-04. Logs never contain bodies, queries, header values, or client addresses. Problem bodies never echo input values. Body and list caps bound CPU and memory per request. Use synthetic data only. Do not expose the server beyond localhost before P2-03 adds identity and rate limits.

**Configuration required**:
- `ENERGYIQ_ENV`: `dev` (default), `test`, or `prod`; `prod` disables the docs routes and default CORS origins.
- `ENERGYIQ_MAX_BODY_BYTES`: request body cap in bytes, default `1048576`, must be positive.
- `ENERGYIQ_CORS_ORIGINS`: JSON list of allowed origins; default depends on `ENERGYIQ_ENV`.
- `ENERGYIQ_LOG_LEVEL`: `DEBUG`, `INFO` (default), `WARNING`, or `ERROR`.

The 5,000 reading and 500 event caps are schema constants, not settings, because they are part of the published contract.

**Critical test scenarios**:
- Happy path: a synthetic chain with a reset event, a flagged reading, and a window crossing an interval returns numbers equal to a direct domain call, verifies **AC-2**, **AC-3**.
- `-04:00` input becomes `Z` output at the same instant; a naive timestamp gets 422 at its path, verifies **AC-4**.
- `cumulative_kwh` as JSON number `13049.0` gets 422; `"1E+2"`, `"1.0000000"`, and `"9999999999999"` get 422 `invalid_kwh`; `"13049.0"` succeeds; a result of `Decimal("0E-8")` prints `"0.00000000"`, verifies **AC-3**, **AC-4**.
- `recorded_at` as JSON number `1700000000` gets 422; `9999-12-31T23:00:00-04:00` gets 422 `datetime_out_of_range`, verifies **AC-4**.
- Exact text: `P1DT2H30M`, `PT0.000001S`, `PT0S`, `2026-10-25T16:00:00Z`, `2026-10-25T16:00:00.000001Z`, verifies **AC-3**.
- Empty readings, a single reading, and only voided readings each return the full `no_intervals` gap, verifies **AC-4**.
- Body with `created_at` gets 422; a frozen clock shows on mapped records, verifies **AC-5**.
- Duplicate reading ids and same instant readings (including a voided one) return their problem codes with indexes; a body with both returns `duplicate_id`, verifies **AC-5a**, **AC-6**, **AC-7**.
- 5,001 invalid readings return exactly 100 `errors[]` items with `errors_truncated: true`, and no item contains the submitted value, verifies **AC-8**.
- A route forced to raise returns 500 with `X-Request-ID`, no exception text, and exactly one logged traceback with the request id, verifies **AC-8**, **AC-10**.
- Empty body and invalid UTF-8 get 400 `malformed_json`; `Content-Length: abc` sent to the app directly (ASGI) gets 400 `invalid_content_length`, and sent to the live uvicorn server gets uvicorn's plain 400; 405 keeps `Allow`, verifies **AC-8**.
- `text/plain` POST to the summary gets 415; `POST /health` gets 405 and `POST /nope` gets 404; a 2 MiB body with and without `Content-Length` gets 413 (never 400); all carry `X-Request-ID`, verifies **AC-9**, **AC-10**.
- An invalid `X-Request-ID` (`"bad id!"`) is replaced; one access log line has exactly the seven keys; two `create_app` calls still log one line per request, verifies **AC-10**.
- `prod` hides docs and installs no CORS; a preflight from `http://localhost:3000` is allowed without credentials; `http://evil.test` never gets `Access-Control-Allow-Origin`, verifies **AC-11**.
- OpenAPI equals the snapshot, has problem schemas only under `application/problem+json`, and has no `HTTPValidationError`; a fresh interpreter import of `energyiq.readings` loads no framework, verifies **AC-12**.
- Live uvicorn subprocess answers `/health` and a summary, verifies **AC-1**, **AC-13**.
- Auth/permission: not applicable until P2-03; the test suite asserts the summary route needs no credentials and sends no `Access-Control-Allow-Credentials`, verifies **AC-11**.

## Build plan

Tracer Bullet (no approach is recorded in the repo, so this is the assumed default): first one thin thread from uvicorn through the domain and back, then thicken each layer.

1. Check the FastAPI, Starlette, uvicorn, pydantic-settings, and httpx docs for Python 3.13 compatibility. Add `fastapi`, `uvicorn`, `pydantic-settings` as runtime dependencies and `httpx` as dev only, pin the tested versions, and update `uv.lock`, satisfies **AC-13**
   - **Deviation (2026-11-03, approved by the user):** the dev test client is `httpx2`, not `httpx`. Starlette 1.10.0 (locked with FastAPI 0.162.0) warns `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead` and types `TestClient` against `httpx2`, so with `httpx` installed strict Pyright reports unknown types on every `TestClient` call (3 errors on a 3 line probe). Every mention of httpx in this spec (AC-13 smoke test, the dev dependency) means `httpx2`.
2. Thin thread: `__version__`, `Settings`, `get_now`, `create_app`, `/health`, the request and response schemas, the mapping, and the summary route on the happy path, plus the live uvicorn smoke test and the version test, satisfies **AC-1**, **AC-2**, **AC-3**
3. Problem framework: `Problem`, `ProblemError`, `problem_response()`, both catalogs, the `RequestValidationError` handler (400 `malformed_json` for JSON decode, UTF-8, and empty body cases, otherwise 422 with mapped and capped `errors[]`), and the Starlette `HTTPException` handler (status to code map, `exc.headers` copied), satisfies **AC-8**
4. Output formatters (`format_decimal`, `format_utc`, `format_duration`) with exact text tests, satisfies **AC-3**
5. Input rules: `KwhString`, `UtcInstant` (strict, UTC conversion, overflow), window check, `extra="forbid"`, list caps, defaults, approval pair check, server `created_at`, satisfies **AC-4**, **AC-5**
6. Duplicate id and timestamp conflict checks in the fixed order, with their problem members, satisfies **AC-5a**, **AC-6**, **AC-7**
7. Pure ASGI middleware: `RequestContextMiddleware` (request id, idempotent JSON access log, owning the 500 path) and `BodySizeLimitMiddleware` (declared and streamed, invalid `Content-Length`), plus the `require_json` dependency, satisfies **AC-8**, **AC-9**, **AC-10**
8. Settings driven docs toggle and conditional CORS, plus startup failure on invalid settings, satisfies **AC-11**
9. OpenAPI `responses` for the Problem schema, the `app.openapi` override for `application/problem+json`, the committed snapshot with a documented regeneration path (`ENERGYIQ_UPDATE_SNAPSHOTS=1`), and the subprocess import boundary test, satisfies **AC-12**
10. Documentation: README run command and curl example, the error table in `docs/04-DATA-MODEL-API.md`, pinned versions in `docs/03-TECH-STACK.md`, `docs/PROGRESS.md`, and the roadmap line; run the full suite, Ruff, format, and Pyright, satisfies **AC-13**

### Implementation deviations (2026-11-04)

Found while building against the locked versions; each keeps the acceptance criteria's intent:

- **Test client:** `httpx2` instead of `httpx` (see build step 1).
- **`UtcInstant`:** `Annotated[AwareDatetime, BeforeValidator(parse_utc_instant)]` in `platform/http/types.py` instead of `Field(strict=True)`. FastAPI validates bodies as Python objects (not `validate_json`), where Pydantic strict mode rejects every ISO string (`datetime_type`), and lax mode accepts JSON numbers and numeric strings such as `"1700000000"` as Unix times. The parser accepts only a JSON string, parsed by `datetime.fromisoformat`, with an explicit offset; it converts to UTC and maps `OverflowError` to `datetime_out_of_range`. `KwhString` also lives in `types.py` for reuse.
- **List cap scenario:** Pydantic checks `max_length` before validating items, so 5,001 readings return one `too_many_items` error, not item errors. The 100 item cap is tested with 5,000 invalid readings instead.
- **Problem extensions:** the generic `Problem` model (platform) has `errors` and `errors_truncated`; the readings specific `duplicates` and `conflicts` live on `ConsumptionProblem(Problem)` in `readings/api/schemas.py`, so `platform` never imports a feature. `errors_truncated` is always present on `validation_error` (`false` when nothing was cut).
- **Invalid UTF-8:** FastAPI raises `HTTPException(400)` for it (not a validation error), so the HTTP handler maps 400 to `malformed_json`.
- **Access log for docs routes:** `route` is the template only for FastAPI `APIRoute` matches, so `/docs`, `/redoc`, `/openapi.json` log `"unmatched"`, as AC-10 requires.
- **Malformed `Content-Length` (AC-8 amended 2026-11-04 after `/check verify`):** on the live server, uvicorn's h11 parser rejects `Content-Length: abc` with `400 Invalid HTTP request received.` (plain text, no `X-Request-ID`) before the app runs, so no app code can answer it. AC-8 now lists it as a second documented exception beside the CORS preflight; the middleware check stays as defense in depth.
- **Disconnect:** when the client disconnects before the response starts, the middleware drops the response messages and logs 499.

## Consequences

**Positive**:
- Every later endpoint (P2-03 onward, P3 client, P7 MCP) inherits one error shape, one value format, and request tracing.
- The Phase 1 domain is proven through a real server with no changes to it.

**Negative / tradeoffs**:
- The summary endpoint accepts client stated approvals and has no auth or rate limit; it is safe only locally, and its long term role is unsettled (see Follow-up).
- Decimal strings and ISO 8601 durations are less convenient for clients than numbers; the P3 client needs a parsing layer.
- Pure ASGI middleware is more code than Starlette's `BaseHTTPMiddleware`, and it must render problems itself.
- The OpenAPI snapshot fails on any FastAPI upgrade that changes generated output; regenerating it becomes part of dependency updates.

**Neutral**:
- Three runtime dependencies and one dev dependency are added. No database, Docker, or new infrastructure.
- `docs/04-DATA-MODEL-API.md` gains the error semantics table that later endpoints extend.

## Follow-up

- [ ] P2-03: add per user rate limiting, 401/403 semantics, and decide whether `/api/v1/consumption/summary` stays public, gets auth, or is retired.
- [ ] P2-04: decide whether the stateless summary stays as a preview endpoint or is replaced by `GET /meters/{id}/consumption` over stored readings; reuse these schemas either way.
- [ ] P2-02: add a readiness check (database) beside `/health`, and `DATABASE_URL` to `Settings`.
- [ ] P3: settle cookie credentials, CSRF, and origin setup (open decision 1) before turning on `allow_credentials`.
- [ ] Agent Skills and MCP servers for FastAPI, uvicorn, and pydantic-settings were deferred ("not now"); a FastAPI conventions skill is the most likely useful one.
- [ ] `/sync`: record FastAPI, uvicorn, pydantic-settings, and httpx, the problem details convention, and the run command in `AGENTS.md`.
