# 0008. Rationale: minimal FastAPI application

## Context

> ⚠️ Premise note: P2-01 comes before persistence (P2-02) and identity (P2-03), so any endpoint with real input is either throwaway or a contract that later tickets must honor. The stateless summary endpoint is useful because it proves the domain over HTTP and fixes the value and error conventions now. But it accepts client stated event approvals, and it has no owner. It must stay local and synthetic, and P2-03 or P2-04 must decide whether it survives. That decision is recorded as a Follow-up, not assumed.

Phase 1 delivered a pure, tested domain: validated readings and events (spec 0002), ordering with conflict groups (spec 0003), interval boundaries (spec 0004), and exact normalization with coverage gaps (spec 0005). It has no HTTP surface. The roadmap's P2-01 asks for a minimal FastAPI app with request and response schemas and explicit HTTP error semantics. `docs/04-DATA-MODEL-API.md` already demands Pydantic models distinct from domain records, clear 400 to 503 semantics, UTC ISO timestamps, a decimal serialization policy, correlation ids, and payload limits, but none of these is defined concretely.

The forces: the domain rejects anything but zero offset UTC datetimes and exact Decimals; money and kWh must never pass through binary floats; the P3 Next.js client and the P7 MCP adapter will consume whatever error and value shapes appear first; the repo rule is to add dependencies and infrastructure only when the phase needs them; and nothing may be stored yet. Without a decision here, each later endpoint invents its own error envelope and number format, and retrofitting them later breaks clients.

## Options considered

### Option 1: Health check and error framework only
The app factory, problem handlers, middleware, and `GET /health`, with no domain endpoint.

**Pros**: smallest surface; nothing to retire later.
**Cons**: request schemas, Decimal and timestamp handling, and domain error mapping stay unproven until P2-03 or P2-04, which then carry persistence, auth, and HTTP contract risk all at once.

### Option 2: Health check plus a stateless consumption summary (chosen)
`GET /health` and `POST /api/v1/consumption/summary`, which maps a posted chain to domain records and returns the summary and intervals.

**Pros**: exercises every convention (decimal strings, UTC conversion, 422 paths, conflicts, limits) against real domain behavior; the schemas carry into P2-04.
**Cons**: an unauthenticated calculation surface whose long term role is open; approvals are client asserted.

### Option 3: Health check plus a two reading delta
`POST /api/v1/consumption/delta` over the Phase 0 function.

**Pros**: tiny schema, quick to build.
**Cons**: skips the Phase 1 interval, event, and coverage contract that every real endpoint will expose; most conventions stay untested.

### Option 4: Separate interval and summary endpoints
Two calculation routes instead of one combined response.

**Pros**: smaller responses per call.
**Cons**: double the surface to test and snapshot, for no client that needs them separately yet.

## Rationale

Option 2 is the cheapest way to make the HTTP conventions real against the actual domain. The value rules (no floats, UTC only) are the riskiest part of the API, and only an endpoint carrying readings tests them. Option 1 defers that risk into the tickets that already carry persistence and auth. Option 3 tests the wrong contract. Option 4 adds surface without a consumer. The cost of Option 2, an endpoint with an open future, is contained by keeping it local, synthetic, and recorded in Follow-up.

The engineer's choices fixed the main conventions: RFC 9457 problem details, decimal strings in both directions, any explicit offset converted to UTC, client ids with server `created_at`, 422 for conflicts, summary plus intervals, 5,000 / 500 / 1 MiB limits, plain `fastapi` + `uvicorn` + `httpx` (dev), pydantic-settings, request id plus JSON access log, a pure ASGI body cap, docs off in prod, unversioned `/health`, CORS for `localhost:3000` without credentials, a required window, empty input allowed, unknown fields rejected, duplicate ids rejected, ISO 8601 durations, 415 for non JSON, one live uvicorn test, and rate limiting deferred to P2-03.

### Sub decisions made in the spec (pick, why, runner up)

| Decision | Pick | Why | Runner up |
|---|---|---|---|
| Problem `type` | `about:blank` plus a stable `code` member | No dereferenceable problem URIs exist yet; `code` gives clients a stable branch key | `urn:energyiq:problem:<code>` per code |
| Malformed JSON | 400 `malformed_json` | Unparseable syntax is a bad request, not a semantic failure; keeps 422 meaning "valid JSON, invalid content" | FastAPI's default 422 `json_invalid` |
| 422 item shape | `{loc, code, message}`, never `input` | Pydantic echoes input by default, which would leak values into logs and clients | Pydantic's raw error list |
| Ids shared across readings and events | Allowed | Outputs reference reading ids and event ids in separate fields, so there is no ambiguity | Reject any shared id |
| Domain errors after mapping | 500; every domain rule lives in the schemas | Domain messages carry no field path, so mapping them to 422 would mean parsing strings | Catch domain errors and map to 422 |
| kWh digit cap | 12 integer, 6 fraction digits in the pattern | Unbounded trailing zeros trip the domain's exact precision 28 context and would 500 | Rely on the domain's range check |
| Datetime input | Strict `AwareDatetime`, string only | Lax mode parses JSON numbers as UTC, bypassing the explicit offset rule | Lax with a custom pre validator |
| Handler style | Sync `def` | The work is pure CPU; async would block the event loop | `async def` with `run_in_threadpool` |
| 415 enforcement | Per route `require_json` dependency | Runs only after routing, so 404 and 405 keep precedence over 415 | Global middleware on write methods |
| 500 path | Owned by `RequestContextMiddleware` | Starlette runs app `Exception` handlers outside user middleware, losing the request id and logging twice | App `Exception` handler |
| Streamed 413 | `HTTPException(413)` from the receive wrapper | FastAPI wraps any other exception from body reading as 400 | Flag in middleware plus rewrite of the 400 |
| CORS when empty | Not installed | Stock middleware still sends some CORS headers to disallowed origins; with no origins there is nothing to allow | Always installed with an empty list |
| Validation messages | Own catalog, capped at 100 | Pydantic messages can quote input, and 5,000 bad items would make a huge body | Pydantic `type` and `msg` uncapped |
| Output formats | Own formatters | Library default text for durations and fractional seconds can change between versions | Pydantic defaults |
| `created_at` source | Injectable `get_now` dependency | Deterministic tests without patching | `datetime.now(UTC)` inline |
| `version` source | `__version__` constant with a pyproject test | The project is not installed as a package, so `importlib.metadata` would fail | `importlib.metadata.version` |
| Logged route | Matched route template, else `"unmatched"` | Raw paths can carry ids or probe strings | Raw path |
| Count caps | Schema constants | They are part of the published contract and appear in OpenAPI | Settings |
| API module home | `readings/api/` beside the domain | Keeps the bounded module together while the domain stays framework free | Top level `energyiq/api/` |
