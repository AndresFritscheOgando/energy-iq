# 0009/0003. Readings, events, and stored consumption (P2-04)

## Summary

This child stores meter readings and meter events, and computes consumption from what is stored. A reading's value and time never change; the owner can only flag or void it. Events (a reset, a replacement) start as pending and the owner approves or rejects them, and only approved events let consumption cross a discontinuity. A repeated POST with the same `Idempotency-Key` returns the first answer instead of writing twice.

## Requirements

**User stories**:
- As an owner, I want to record a reading by exact time or just by date, and see it listed in order.
- As an owner, I want to void a typo and record a reset, so my consumption numbers stay right.
- As the P3 client on a flaky network, I want to retry a POST safely.
- As the P3 chart, I want measured consumption and coverage for a window over stored data.

**Acceptance criteria**:
- **AC-1**: `POST /api/v1/meters/{id}/readings` `{recorded_at | local_date, cumulative_kwh, status?, source?}` stores one reading and returns 201 `ReadingOut`. Exactly one of `recorded_at` and `local_date` is required (422 `exactly_one_of`). `cumulative_kwh` uses the 0008 `KwhString` rule; `status` is `valid` (default) or `flagged` (`voided` is not accepted at creation); `source` is `manual` (default) or `import`. `recorded_at` later than now plus 5 minutes, or `local_date` later than today in the property's time zone, is 422 `reading_in_future`. A decrease from the previous reading is stored as given (consumption reports it as `unexplained_decrease`).
- **AC-2**: Date only input: `local_date` `D` becomes `recorded_at = datetime.combine(D, time(12), ZoneInfo(property.timezone)).astimezone(UTC)` and `original_local_date = D`. For `America/Santo_Domingo`, `2026-11-03` stores `2026-11-03T16:00:00Z`. A second date only reading for the same date (or any reading at the same instant) returns 409 `reading_exists_at_instant` with `existing_reading_id`, unless the existing one is voided.
- **AC-3**: Same instant rule: a reading whose `(meter_id, recorded_at)` matches a non voided reading returns 409 `reading_exists_at_instant`. Under the meter row lock, the use case first selects a non voided reading at that instant; if one exists it raises 409 with its id (race free, since the lock serializes writers to the meter). `uq_readings_meter_instant_active` stays as the backstop: if it still fires, the transaction is rolled back, the existing id is read in a new transaction, and the same 409 is returned. Two racing requests give exactly one 201.
- **AC-4**: `GET /api/v1/meters/{id}/readings?from=&to=&status=&limit=&cursor=` returns `Page[ReadingOut]` ordered by `(recorded_at, id)` ascending, all statuses unless `status` filters one (an unknown value is 422 `invalid_enum`). `from` and `to` are each optional, with explicit offsets: `from` alone means `recorded_at >= from`, `to` alone means `recorded_at < to`, both mean `[from, to)` and require `from < to` (422 `range_order`). There is no window cap, because pagination bounds each page. `cumulative_kwh` is rendered with exactly six fraction digits (the stored `NUMERIC(18,6)` form, for example `"13049.000000"`).
- **AC-5**: `PATCH /api/v1/meters/{id}/readings/{reading_id}` `{status}` changes only the status. Allowed: `valid → flagged`, `valid → voided`, `flagged → valid`, `flagged → voided`; the same status (including `voided → voided`) is a 200 no op with no audit row; any change from `voided` to another status is 409 `reading_voided`. It sets `status_changed_at` and writes `reading.status_change` with `{"from", "to"}`. It works on inactive meters. No route changes `cumulative_kwh`, `recorded_at`, or deletes a reading.
- **AC-6**: Events: `POST /api/v1/meters/{id}/events` `{event_type, effective_at, note?}` → 201 `EventOut` with `status: pending` (`effective_at` future rule as AC-1; `note` is trimmed, at most 500 characters, and an empty result is stored as null, so the domain never receives a blank note). `GET /api/v1/meters/{id}/events?status=&limit=&cursor=` → `Page[EventOut]` by `(effective_at, id)`. `POST .../events/{event_id}/approve` and `.../reject` set `status`, `decided_by` (current user), `decided_at` and return 200; a non pending event returns 409 `event_not_pending`. Approve and reject work on inactive meters.
- **AC-7**: Creating a reading or event on an inactive meter returns 409 `meter_inactive`. Every reading and event write locks the meter row first. Meter, property ownership, and archive rules from child 0002 apply (404).
- **AC-8**: Idempotency (revision `0003`, table `idempotency_keys`): every authenticated `POST` that creates or decides (properties, meters, deactivate, readings, events, approve, reject) declares the `idempotent` dependency (which tests use to enumerate these routes) and accepts an optional `Idempotency-Key` header (1 to 255 visible ASCII characters, else 400 `invalid_idempotency_key`). Mechanics, in order, inside the write transaction:
  1. The key statement is the **first** statement of the transaction, before the meter lock: `INSERT ... VALUES (user_id, key, operation, request_hash, created_at = now, expires_at = now + 24h) ON CONFLICT (user_id, key) DO UPDATE SET operation, request_hash, response_status = NULL, response_body = NULL, created_at, expires_at = EXCLUDED... WHERE idempotency_keys.expires_at <= :now RETURNING user_id`, with `now` from the injected clock (never database `now()`).
  2. A returned row means this request owns the key: run the use case, render the response body to bytes with the 0008 formatters, `UPDATE` the row with `response_status` and `response_body`, commit, and return a raw `Response` with those exact bytes and `Content-Type: application/json`.
  3. No returned row means a live row exists. A concurrent owner's uncommitted insert makes step 1 wait until it ends. If it committed, a new `SELECT` (READ COMMITTED sees the commit) reads the row: same `operation` and `request_hash` → replay the stored status and bytes with `Content-Type: application/json` and `Idempotent-Replayed: true`, plus a new `X-Request-ID`, and no write or audit; otherwise 409 `idempotency_key_reused`. If the owner rolled back, step 1 inserts and this request becomes the owner.
  4. A replay wins over every later check (a since archived property or deactivated meter still replays the original 201).
  `operation` is `"<METHOD> <route template>"` plus the path parameter values in template order, for example `POST /api/v1/meters/{id}/readings 7f1c...`. `request_hash` is SHA-256 of `json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))`, or `sha256(b"")` for bodyless POSTs. Only successful responses are stored; a failed write rolls the key back, so a retry runs again.
- **AC-9**: `GET /api/v1/meters/{id}/consumption?from=&to=` (both required, explicit offsets, `to > from`, at most 366 days, else 422 `range_order` or `window_too_long` at `["query", "to"]`) returns the 0008 `ConsumptionSummaryResponse`, except that `intervals[]` holds only the intervals overlapping `[from, to)` (in time order, each with `measured_in_window`), not every interval of the loaded chain. It loads non voided readings with `recorded_at` in `[from, to)`, plus the latest non voided reading before `from` and the earliest at or after `to`, and the non rejected events with `effective_at` in `(first loaded recorded_at, last loaded recorded_at]`. Pending events map to unapproved domain events; approved ones carry `approved_by = decided_by` and `approved_at = decided_at`. Oracle: the summary fields and the overlapping `intervals[]` equal a direct domain call over the meter's entire **non voided** stored history and its non rejected events for the same window, with that call's intervals filtered to those overlapping the window (property test over generated histories, which include voided readings sharing an instant with live ones).
- **AC-10**: Every write audits in its transaction (`reading.create`, `reading.status_change`, `event.create`, `event.approve`, `event.reject`), with metadata free of kWh values and note text. `docs/12-METER-SEMANTICS.md` records that stored readings reject same instant collisions (E13 becomes a 409 for stored data, while the stateless summary keeps the P1-02 conflict report).

## Decision

Single reading POSTs with immutable values and status only corrections, a pending → approved or rejected event lifecycle, `Idempotency-Key` rows committed with the write, a meter row lock per write, keyset lists, and a stored consumption read that reuses the Phase 1 domain unchanged.

Short rationale: see the umbrella [rationale](rationale.md).

## Feature design

**Data model** (revision `0003`):

| Table | Columns | Constraints and indexes |
|---|---|---|
| `idempotency_keys` | `user_id uuid` · `key text` (1 to 255) · `operation text` · `request_hash bytea` (32) · `response_status smallint` null until the write completes · `response_body bytea` null (the exact response bytes; `jsonb` would reorder keys) · `created_at` · `expires_at` | `pk_idempotency_keys` on `(user_id, key)`; FK to `users`; `ix_idempotency_keys_expires_at` |

The row is inserted first with NULL response columns and updated before commit, so a committed row always has a response. Revision `0003` grants `energyiq_app` `SELECT, INSERT, UPDATE` on `idempotency_keys` (all columns, needed by the expired row overwrite), revoked in `downgrade()`.

**State transitions**:
- Reading status: `valid ⇄ flagged`, `valid → voided`, `flagged → voided`; `voided` is terminal.
- Event status: `pending → approved`, `pending → rejected`; both terminal.

**Response models**: `ReadingOut {id, meter_id, recorded_at, original_local_date, cumulative_kwh, source, status, created_at, status_changed_at}` · `EventOut {id, meter_id, event_type, effective_at, status, note, created_by, created_at, decided_by, decided_at}` · consumption reuses `ConsumptionSummaryResponse` from 0008.

**API surface** (under `/api/v1`; session required; CSRF on unsafe methods; `Idempotency-Key` optional on POST):
| Endpoint | Method | Key inputs | Key outputs | Key errors |
|---|---|---|---|---|
| `/meters/{id}/readings` | POST | `recorded_at` or `local_date`, `cumulative_kwh`, `status?`, `source?` | 201 `ReadingOut` | 404, 409 `meter_inactive` / `reading_exists_at_instant` / `idempotency_key_reused`, 422 |
| `/meters/{id}/readings` | GET | `from?`, `to?`, `status?`, `limit`, `cursor` | `Page[ReadingOut]` | 404, 422 |
| `/meters/{id}/readings/{reading_id}` | PATCH | `status` | `ReadingOut` | 404, 409 `reading_voided`, 422 |
| `/meters/{id}/events` | POST | `event_type`, `effective_at`, `note?` | 201 `EventOut` | 404, 409 `meter_inactive`, 422 |
| `/meters/{id}/events` | GET | `status?`, `limit`, `cursor` | `Page[EventOut]` | 404, 422 |
| `/meters/{id}/events/{event_id}/approve` | POST | none | `EventOut` | 404, 409 `event_not_pending` |
| `/meters/{id}/events/{event_id}/reject` | POST | none | `EventOut` | 404, 409 `event_not_pending` |
| `/meters/{id}/consumption` | GET | `from`, `to` | `ConsumptionSummaryResponse` | 404, 422 `range_order` / `window_too_long` |

A reading or event id under the wrong meter is 404, even when both belong to the caller.

**Value sourcing**:
| Action | Value | Source |
|---|---|---|
| create reading | `recorded_at` (date only) | `local_date` input plus `properties.timezone` via the meter's property, noon local, to UTC |
| create reading | `original_local_date` | `local_date` input; null for exact time input |
| create reading | "now" and "today" for the future rule | injected clock; today in `properties.timezone` |
| create reading | `id`, `created_at`, `created_by` | `uuid4()`, clock, current user |
| create reading | `existing_reading_id` on 409 | SELECT of the non voided reading at that instant under the meter lock (or, after a backstop `IntegrityError`, in a new transaction) |
| status change | `status_changed_at` | clock |
| event decide | `decided_by`, `decided_at` | current user, clock |
| idempotency | `operation` | `"<METHOD> <route template>"` plus path parameter values in template order |
| idempotency | `request_hash` | SHA-256 of `json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))`, or `sha256(b"")` for bodyless POSTs |
| idempotency | `created_at`, `expires_at` | injected clock, plus 24 hours |
| idempotency | replayed body and status | `idempotency_keys.response_body` bytes, `response_status`; `Content-Type: application/json` |
| consumption | `intervals[]` | normalized intervals of the loaded chain, filtered to those overlapping `[from, to)` |
| event create | stored `note` | input trimmed; empty becomes null |
| consumption | domain `Reading` fields | `readings` rows (UTC normalized, `Decimal` from NUMERIC) |
| consumption | domain `MeterEvent.approved_by`, `approved_at` | `decided_by`, `decided_at` when `status = 'approved'`, else None |
| consumption | window | `from`, `to` query parameters (0008 `UtcInstant` parsing) |
| consumption | all summary numbers | `summarize_consumption` and `normalize_intervals` (specs 0005, 0008 mapping) |
| list | `cumulative_kwh` text | `format(value, "f")` of the stored `Decimal` (scale 6) |

**Key invariants**:
- The stored non voided readings of a meter never share an instant, so `order_readings` on them never reports a conflict; a conflict there is a bug (500).
- Rejected events never reach the domain; pending events block exactly as unapproved events do in P1-03.
- One transaction holds the idempotency row, then the meter lock, the write, and the audit row, always in that order.
- No numeric value is computed or stored at write time (consumption is computed at read time).

**Security model**: owner scoped through the meter lookup (child 0002). Event approval is an owner's recorded decision with actor and time, which replaces the client stated approvals of the stateless summary. Idempotency keys are scoped per user, so one user's key never replays for another. Notes are owner data: returned only to the owner, never logged or audited.

**Configuration required**: none beyond the umbrella.

**Critical test scenarios**:
- Exact time and date only readings stored and listed in order; `local_date` 2026-11-03 → `16:00:00Z`, verifies **AC-1**, **AC-2**, **AC-4**
- Second reading at the same instant → 409 with `existing_reading_id`; after voiding the first, the same POST → 201, verifies **AC-2**, **AC-3**, **AC-5**
- Two threads (separate connections, committed data) post the same instant → one 201, one 409, verifies **AC-3**
- Status matrix: every allowed and forbidden transition, including voided terminal and same status no op, verifies **AC-5**
- Decrease with a pending reset → invalid interval; approve the reset → valid intervals; reject instead → `unexplained_decrease`, verifies **AC-6**, **AC-9**
- Inactive meter: POST reading or event → 409; PATCH status and approve still work, verifies **AC-7**
- Idempotency: replay byte identical body and same status with `Idempotent-Replayed: true`, one row and one audit; changed body → 409; failed first attempt (409 instant) then retry with a fixed body → 201; expired key reused → new write; replay after the meter was deactivated still returns the original 201; first owner rolls back while a second request waits → the waiter writes, verifies **AC-8**
- Blank note `"   "` → stored null; consumption over that event → 200, verifies **AC-6**, **AC-9**
- Consumption oracle: generated histories (Hypothesis, the 0006 strategies) with random windows equal a direct domain call on the full history; 367 day window → 422, verifies **AC-9**
- Audit rows contain no kWh or note text, verifies **AC-10**

## Build plan

1. Thin thread: reading ORM repository, `POST` and `GET /meters/{id}/readings` with exact time input, meter lock, audit, end to end, satisfies **AC-1**, **AC-4**, **AC-7**
2. Same instant 409 with `existing_reading_id`, future rule, and date only conversion through the property time zone, satisfies **AC-1**, **AC-2**, **AC-3**
3. Reading status PATCH with the transition table, satisfies **AC-5**
4. Events: create, list, approve, reject, inactive rules, satisfies **AC-6**, **AC-7**
5. Revision `0003` and `platform/idempotency.py`; apply it to every authenticated create or decide POST, including the child 0002 routes, satisfies **AC-8**
6. Row to domain mapping and `GET /meters/{id}/consumption` with the loading rule and the oracle property test, satisfies **AC-9**
7. Audit metadata checks and the meter semantics doc update, satisfies **AC-10**
