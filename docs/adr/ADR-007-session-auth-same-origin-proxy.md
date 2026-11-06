# Server sessions in an HttpOnly cookie, behind a same origin proxy

**Status:** Accepted
**Date:** 2026-11-04
**Context:** Phase 2 adds accounts, and every stored property, meter, reading, and event is private to its owner. The P3 Next.js client runs in a browser, so the API needs an authentication method a browser can carry safely. Logout and account disable must take effect at once, and no credential may be readable by page scripts or show up in logs. The 0008 CORS policy is credential free (`allow_credentials=False`), and keeping it that way removes a class of cross origin mistakes. This closes open decision 1 in [11-DECISIONS](../11-DECISIONS-OPEN-QUESTIONS.md). Decided in [spec 0009](../specs/0009-phase-two-persistence-auth/index.md) ([rationale](../specs/0009-phase-two-persistence-auth/rationale.md)), built in [child 0002](../specs/0009-phase-two-persistence-auth/0002-identity-properties-meters.md).

## Decision
- **Opaque server sessions.** Login and register create a `sessions` row and send a random token (`secrets.token_urlsafe(32)`, 256 bits) in a cookie. Only `sha256(token)` is stored. A session ends on logout, at 14 days absolute, or after 24 hours idle (the idle touch is written at most every 5 minutes). Login revokes any session the request already carried, which defends against session fixation. A disabled user's sessions stop working on their next request.
- **Cookie.** `energyiq_session` with `HttpOnly`, `SameSite=Lax`, `Path=/`, no `Domain`, `Max-Age` 14 days. When `ENERGYIQ_SESSION_COOKIE_SECURE` is true (the `prod` default), the cookie is `Secure` and named `__Host-energyiq_session`.
- **CSRF.** Every unsafe method under `/api/v1` requires `X-EnergyIQ-CSRF: 1`. A custom header forces a CORS preflight, so a cross site form cannot send it. When `Origin` is present it must equal the request's own origin or one of `ENERGYIQ_TRUSTED_ORIGINS`, and `Origin: null` is rejected. Failures return 403 `csrf_rejected`.
- **Passwords.** Argon2id through `argon2-cffi` (RFC 9106 low memory profile; the cheapest profile in tests), 12 to 128 characters after NFKC, rehashed on login when the profile changes. An unknown email still runs one verification against a dummy hash, so timing does not reveal accounts.
- **Rate limits** for login and register are stored in PostgreSQL (`auth_attempts`), keyed by HMAC of the email or client address, never the raw value, and answered with 429 and `Retry-After`.
- **Same origin proxy for browsers.** The P3 Next.js server rewrites `/api` to FastAPI, so the browser sees one origin and sends the cookie as first party. CORS stays credential free.
- **401 without `WWW-Authenticate`.** Cookie sessions have no registered HTTP auth scheme; this deviation from RFC 9110 is documented in [04-DATA-MODEL-API](../04-DATA-MODEL-API.md).

## Alternatives considered
- **JWT access tokens (bearer or cookie).** Stateless, but logout and disable cannot take effect before expiry without a denylist, which is a session table by another name. A bearer token in browser storage is readable by any injected script.
- **Credentialed CORS** from the Next.js origin straight to FastAPI. It works, but it needs `allow_credentials=True`, an exact origin list kept in sync, and `SameSite=None` if the hosts differ. The proxy avoids all three.
- **Double submit CSRF token.** Equivalent protection, but it adds a token endpoint and client state. The header plus `Origin` check needs neither.
- **`SameSite=Strict`.** It would drop the cookie when a user follows a link into the app from elsewhere. `Lax` plus the CSRF header already blocks cross site writes.

## Consequences
- Sessions are revocable at once, and the browser never holds a credential that scripts can read.
- Every request costs one indexed session lookup; that is fine at household scale.
- P3 must ship the `/api` rewrite and send `X-EnergyIQ-CSRF: 1` on unsafe requests (P3-01 follow up).
- Non browser clients (CLI, MCP tools) need a cookie jar until a token path is designed in P7. Any such path must keep the owner scoping and audit rules and must not weaken the browser flow.
- Expired sessions and attempt rows accumulate until `python -m energyiq.platform.maintenance` runs; scheduling it is a P8 task.
- Email verification and breached password checks are deferred (P8 follow ups in spec 0009).

## Revisit trigger
A client that cannot hold cookies becomes a requirement (P7 agents or MCP), the API and UI must be served from different sites, or multi user load makes the per request session lookup measurable.
