# 0009/0002. Identity, properties, and meters (P2-03)

## Summary

This child adds accounts and owner scoped data. Users register and log in with email and password. The server keeps a session and gives the browser only a random token in an HttpOnly cookie (a cookie scripts cannot read). Logged in users create, list, rename, and archive their properties, and add and deactivate meters. Another user's data always looks like it does not exist (404).

## Requirements

**User stories**:
- As a new user, I want to register and be signed in at once, so I can start adding my home.
- As an owner, I want my properties and meters private to me, with names I can tell apart.
- As an owner replacing a physical meter, I want to deactivate the old meter and add a new one (ADR-006).

**Acceptance criteria**:
- **AC-1**: `POST /api/v1/auth/register` `{email, password}` normalizes the email (NFKC, trim, lowercase; must contain one `@` with non empty local and domain parts, no whitespace, at most 254 characters, else 422 `invalid_email`) and the password (NFKC; 12 to 128 characters, else 422 `password_length`; no composition rules). It creates the user with an Argon2id hash, creates a session, sets the cookie, writes `auth.register`, and returns 201 `UserOut`. An existing email returns 409 `email_taken`. The response never contains the hash.
- **AC-2**: `POST /api/v1/auth/login` `{email, password}` returns 200 `UserOut` and sets a new session cookie when the credentials match an enabled user. An unknown email, wrong password, or disabled user all return 401 `invalid_credentials` with identical bodies, and an unknown email still runs one Argon2 verification against a fixed dummy hash, so timing does not reveal the account. A valid session cookie sent with the login is revoked (session fixation defense). A successful verify whose hash `check_needs_rehash` flags is rehashed. Success writes `auth.login`; failure writes `auth.login_failed` (actor null, entity the user id if one matched). The failed attempt row and the `auth.login_failed` audit row are committed in their own transaction before the 401 is raised; likewise a register attempt row (and an audit row for `email_taken`) commits before the 409. A test proves a failed login leaves both rows.
- **AC-3**: The session token is `secrets.token_urlsafe(32)`; only `sha256(token)` is stored. The cookie is `energyiq_session` (named `__Host-energyiq_session` when `ENERGYIQ_SESSION_COOKIE_SECURE` is true) with `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age=1209600`, `Secure` per setting, and no `Domain`. A session is valid only when not revoked, `now < expires_at` (login plus 14 days), `now < last_seen_at + 24h`, and the user is not disabled. `last_seen_at` is updated only when at least 5 minutes old. Every `/api/v1` route except register, login, and logout requires a valid session, else 401 `not_authenticated`. Tests of the `Secure` `__Host-` cookie use a `TestClient` with `base_url="https://testserver"`, since httpx does not send a `Secure` cookie over plain http.
- **AC-4**: `POST /api/v1/auth/logout` revokes the current session (if any), clears the cookie (`Max-Age=0`), writes `auth.logout` when a session existed, and returns 204 either way. `GET /api/v1/auth/me` returns `UserOut`. A revoked, expired, or idle session returns 401 on its next use.
- **AC-5**: CSRF: every `POST`, `PATCH`, `DELETE` route under `/api/v1` (including register, login, logout, and the stateless summary) requires the header `X-EnergyIQ-CSRF: 1`. When `Origin` is present it must equal the request's own origin (scheme as seen by the app plus the `Host` header) or one of `ENERGYIQ_TRUSTED_ORIGINS`; `Origin: null` is rejected; a missing `Origin` passes on the header check alone. Failures return 403 `csrf_rejected`. The check is a router level dependency, and a test walks `app.routes` to prove every unsafe method route has it.
- **AC-6**: Rate limits, stored in `auth_attempts` (revision `0002`): login is refused with 429 `too_many_attempts` and `Retry-After` when the normalized email has 5 or more failed attempts in the last 15 minutes since its last success, or the client has 20 or more login attempts in the last 15 minutes; register is refused when the client has 5 or more register attempts in the last hour. Client limits count every attempt, successful or not; the email limit counts failures only. The check runs before password verification, under `pg_advisory_xact_lock` keyed on the first 8 bytes (signed bigint) of the email key for login, or of the client key for register, held until the attempt row commits, so parallel requests cannot overshoot the email limit (the client limit for login is approximate by a few requests, accepted). Refused requests are not recorded as attempts. For each limit hit, with `n` counted attempts and limit `L`, `Retry-After` is `ceil(t + window − now)` seconds, where `t` is the `attempted_at` of the `(n − L + 1)`th oldest counted attempt; when both login limits hit, the larger value; at least 1. `email_key` and `client_key` are `HMAC_SHA256(ENERGYIQ_SECRET_KEY, value)`; no raw email or IP is stored. The client value is `request.client.host` (uvicorn applies `X-Forwarded-For` only from its trusted proxy list, loopback by default).
- **AC-7**: Properties: `POST /api/v1/properties` `{nickname, region?, timezone?}` → 201; `GET /api/v1/properties` → the caller's non archived properties, paginated by `(created_at, id)`; `GET /api/v1/properties/{id}` → 200; `PATCH /api/v1/properties/{id}` with any of `nickname`, `region` (null clears it), `timezone` → 200 (an empty body is 422 `empty_patch`); `DELETE /api/v1/properties/{id}` sets `archived_at` and `updated_at` and returns 204. `region` is trimmed, at most 80 characters, and an empty string is stored as null. Nickname is trimmed, 1 to 80 characters (422 `invalid_text_length`), and unique case insensitively among the owner's non archived properties (409 `property_name_taken`). `timezone` must be in `zoneinfo.available_timezones()` (422 `invalid_timezone`) and defaults to `America/Santo_Domingo`. An archived property, and its meters and their readings and events, return 404 everywhere afterwards. Changing `timezone` does not alter stored readings.
- **AC-8**: Meters: `POST /api/v1/properties/{id}/meters` `{distributor, label, register_digits?}` → 201 active meter; `GET /api/v1/properties/{id}/meters?include_inactive=false` → paginated; `GET /api/v1/meters/{id}` → 200; `PATCH /api/v1/meters/{id}` with `label` and/or `register_digits` → 200; `POST /api/v1/meters/{id}/deactivate` → 200 with `active: false`, `deactivated_at` and `updated_at` set. Label trimmed, 1 to 60 characters, unique case insensitively among the property's active meters (409 `meter_label_taken`), so a replacement meter may reuse a deactivated meter's label. `register_digits` is an integer 4 to 9 or null (422 `invalid_register_digits`). PATCH or deactivate on an inactive meter returns 409 `meter_inactive`. There is no reactivation. PATCH and deactivate lock the meter row (by id and ownership only) and check `active` after the lock, so a concurrent deactivate gives 409, never 404.
- **AC-9**: Ownership: every property and meter lookup joins `owner_user_id = current user` and `archived_at IS NULL` in one statement; another user's id, an archived id, and a random UUID return the same 404 `not_found` body (apart from `request_id`). Lists never include another user's rows.
- **AC-10**: Every create, update, archive, and deactivate writes its audit action in the same transaction (metadata: changed field names only). The stateless `POST /api/v1/consumption/summary` now requires a session and CSRF header; its 200 body is unchanged. The OpenAPI snapshot is regenerated and lists 401, 403, 409, 429, 503 where they apply.
- **AC-11**: `uv run python -m energyiq.platform.maintenance` connects with `ENERGYIQ_MIGRATION_DATABASE_URL` (the app role cannot delete) and, in one transaction, deletes `auth_attempts` older than 24 hours, sessions whose `expires_at` or `revoked_at` is more than 30 days past, and (once child 0003 adds the table) `idempotency_keys` past `expires_at`. It prints one count per table, never row contents, and exits 0; a missing DSN in `prod` exits 2 with the field name. A `db_commit` test seeds old and fresh rows and asserts only the old ones go.
- **AC-12**: Revision `0002` grants `energyiq_app` `SELECT, INSERT` on `sessions` and `auth_attempts` and `UPDATE (last_seen_at, revoked_at)` on `sessions`, revoked in `downgrade()`.

## Decision

Server side sessions with hashed opaque tokens in a `SameSite=Lax` HttpOnly cookie, Argon2id through argon2-cffi, a header plus Origin CSRF check, database backed attempt counting, and owner scoped repositories for properties and meters.

Short rationale: see the umbrella [rationale](rationale.md) (sessions over JWTs, CSRF approach, rate limits, soft delete, building blocks for replacement).

## Feature design

**Data model** (revision `0002`):

| Table | Columns | Constraints and indexes |
|---|---|---|
| `sessions` | `id uuid` · `user_id uuid` · `token_hash bytea` (32 bytes) · `created_at` · `last_seen_at` · `expires_at` · `revoked_at` null | `pk_sessions`; FK and `ix_sessions_user_id`; `uq_sessions_token_hash`; CHECK `octet_length(token_hash) = 32` |
| `auth_attempts` | `id bigint` identity · `kind text` CHECK in (`login`, `register`) · `email_key bytea` null · `client_key bytea` · `succeeded boolean` · `attempted_at` | `ix_auth_attempts_email_key` on `(email_key, attempted_at)`; `ix_auth_attempts_client_key` on `(client_key, attempted_at)` |

**State transitions**:
- Session: active → revoked (logout, re login with that cookie) or expired (absolute or idle). Terminal either way.
- Property: active → archived (terminal in Phase 2).
- Meter: active → inactive (terminal; replacement uses a new meter).

**Response models**: `UserOut {id, email, created_at}` · `PropertyOut {id, nickname, region, timezone, created_at, updated_at}` · `MeterOut {id, property_id, distributor, label, register_digits, active, deactivated_at, created_at, updated_at}` · `Page[T] {items, next_cursor}`. Request models are `extra="forbid"`; server owned fields (`id`, `owner_user_id`, `active`, timestamps) are not accepted.

**API surface** (all under `/api/v1`; every unsafe method also needs the CSRF header):
| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/auth/register` | POST | `email`, `password` | 201 `UserOut`, cookie | public | 409 `email_taken`, 422, 429 |
| `/auth/login` | POST | `email`, `password` | 200 `UserOut`, cookie | public | 401 `invalid_credentials`, 429 |
| `/auth/logout` | POST | cookie | 204, cleared cookie | optional (no 401) | 403 |
| `/auth/me` | GET | cookie | `UserOut` | session | 401 |
| `/properties` | POST | `nickname`, `region?`, `timezone?` | 201 `PropertyOut` | session | 409 `property_name_taken`, 422 |
| `/properties` | GET | `limit`, `cursor` | `Page[PropertyOut]` | session | 422 `invalid_cursor` |
| `/properties/{id}` | GET, PATCH, DELETE | patch fields | `PropertyOut` / 204 | session | 404, 409, 422 `empty_patch` |
| `/properties/{id}/meters` | POST | `distributor`, `label`, `register_digits?` | 201 `MeterOut` | session | 404, 409 `meter_label_taken`, 422 |
| `/properties/{id}/meters` | GET | `include_inactive`, `limit`, `cursor` | `Page[MeterOut]` | session | 404 |
| `/meters/{id}` | GET, PATCH | `label?`, `register_digits?` | `MeterOut` | session | 404, 409 `meter_inactive`, `meter_label_taken` |
| `/meters/{id}/deactivate` | POST | none | `MeterOut` | session | 404, 409 `meter_inactive` |

POST creates here also accept `Idempotency-Key` (mechanics in child 0003; that child adds the table, so these routes gain it there).

**Value sourcing**:
| Action | Value | Source |
|---|---|---|
| any route | current user | `sessions` row found by `sha256(cookie)` joined to `users` |
| register, login | `email_key`, `client_key` | HMAC of normalized email and `request.client.host` with `Settings.secret_key` |
| login | dummy hash | one Argon2 hash computed at app startup from a random value |
| session | `expires_at`, `last_seen_at` | injected clock: login instant plus 14 days; touch instant |
| CSRF | allowed origins | request scheme (after uvicorn's loopback only proxy header handling) plus `Host` header, plus `Settings.trusted_origins` |
| rate limit | `Retry-After` | `auth_attempts.attempted_at` of the `(n − L + 1)`th oldest counted row, window length, injected clock |
| maintenance | retention cutoffs | constants: 24 hours (attempts), 30 days past expiry (sessions), `expires_at` (keys) |
| property | `owner_user_id` | current user, never the body |
| property | default timezone | constant `America/Santo_Domingo` (column default too) |
| meter | `property_id` | path, resolved through the owner scoped lookup |
| any create | `id`, `created_at`, `updated_at` | `uuid4()`, injected clock |
| audit | `request_id` | `scope["state"]["request_id"]` from the 0008 middleware |
| Argon2 parameters | profile | `argon2.profiles.CHEAPEST` when `env=test`, else `RFC_9106_LOW_MEMORY` |

**Key invariants**:
- No route reads another owner's row, even transiently.
- The raw token exists only in the `Set-Cookie` header and the client; logs and audit never contain it.
- Login and register responses are produced only after the attempt row and audit row commit.
- `__Host-` cookie name whenever `Secure` is on.

**Security model**: OWASP session guidance (random 256 bit tokens, hashed at rest, regenerated at login, server side revocation, idle and absolute timeouts). Passwords are Argon2id hashed and bounded at 128 characters against hash cost abuse. Registration admits enumeration via 409; per client throttling bounds it, and email verification is deferred. Only synthetic test data; no PII in logs (0008 rule), and audit metadata never contains email or nicknames.

**Configuration required**: `ENERGYIQ_SECRET_KEY`, `ENERGYIQ_SESSION_COOKIE_SECURE` (umbrella).

**Critical test scenarios**:
- Register → `/auth/me` → logout → `/auth/me` 401, verifies **AC-1**, **AC-3**, **AC-4**
- Unknown email, wrong password, and disabled user give byte identical problem bodies apart from `request_id`; the dummy verify is called once (spy), verifies **AC-2**
- Frozen clock at 24h + 1 µs idle and at 14 days → 401; touch skipped under 5 minutes, verifies **AC-3**
- Missing CSRF header, `Origin: http://evil.test`, and `Origin: null` → 403; same origin → passes; route walk finds no unprotected unsafe route, verifies **AC-5**
- Five failed logins → sixth 429 with `Retry-After`; success resets the email counter; twenty logins from one client → 429; DB rows hold no raw email or IP, verifies **AC-6**
- Duplicate nickname (`Casa` vs ` casa `) → 409; archive frees the name; archived property's meter → 404, verifies **AC-7**, **AC-9**
- Deactivate then create a meter with the same label → 201; PATCH the inactive meter → 409, verifies **AC-8**
- Audit rows exist for each write with field names only, verifies **AC-10**

## Build plan

1. Add `argon2-cffi` (verify docs, pin); revision `0002` with `sessions`, `auth_attempts`, and their grants, satisfies **AC-3**, **AC-6**, **AC-12**
2. Thin thread: register, session creation, cookie, `get_current_user`, `GET /auth/me`, end to end against the database, satisfies **AC-1**, **AC-3**
3. Login (dummy hash, rehash, fixation defense), logout, idle and absolute expiry, satisfies **AC-2**, **AC-4**
4. CSRF dependency on every unsafe `/api/v1` router, the route walk test, and the CORS header and method additions, satisfies **AC-5**
5. Attempt recording, limit checks, `Retry-After`, satisfies **AC-6**
6. `platform/audit.py` and `platform/pagination.py`; property repository and routes with archive, satisfies **AC-7**, **AC-9**, **AC-10**
7. Meter repository and routes with deactivate and the row lock, satisfies **AC-8**, **AC-9**, **AC-10**
8. Put the stateless summary behind session and CSRF; regenerate the OpenAPI snapshot, satisfies **AC-10**
9. `platform/maintenance.py` purge command and its test, satisfies **AC-11**
