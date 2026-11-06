# 0010. Next.js foundation with a typed API layer and browser session

**Date**: 2026-11-04
**Status**: Accepted
**Updated**: 2026-11-05 (AC-14 and AC-18 verified; fresh model reviews approved)

## Summary

This spec covers P3-01, the first piece of the browser app. It sets up a Next.js app in `frontend/`, generates a typed API client from the backend's committed OpenAPI file, and makes sign in, sign up, and sign out work end to end through a same origin proxy (the browser only ever talks to the Next.js server, which forwards `/api` to FastAPI). Every rule that all later screens need lives in one place: the CSRF header, cookie forwarding, error shapes, the session check, and what happens when the API is down. It also fixes a backend gap the proxy would otherwise open: login rate limits must still see each browser's real address. A live check on 2026-11-05 showed the Next.js proxy does not send that address by itself, so a small `proxy.ts` and one setting decide what the address header may carry (AC-18).

## Requirements

**User stories**:
- As a resident, I want to sign up, sign in, and sign out in the browser, so I can reach my private energy data without ever handling a token.
- As a signed in resident, I want a page I open later to tell me plainly when my session has ended, so I am never shown stale or someone else's data.
- As the engineer building P3-02 to P3-04, I want one typed, tested way to call the API from server and browser, so each new screen adds only its own logic.
- As an operator, I want login rate limits to stay per client behind the proxy, so one attacker cannot lock every user out.

**Acceptance criteria**:
- **AC-1**: Workspace. `frontend/` is a Next.js App Router app in strict TypeScript with a `src/` directory, managed by pnpm, with a committed `pnpm-lock.yaml`, a `packageManager` field, and `engines.node` `>=24`. Scripts: `dev`, `build`, `start`, `lint`, `typecheck` (`tsc --noEmit`), `test` (Vitest, run once), `format:check` (Prettier), `gen:api` (Orval). `pnpm build`, `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `pnpm format:check` all pass. Every dependency is pinned to the exact version that was tested.
- **AC-2**: Same origin proxy. `next.config.ts` rewrites `/api/:path*` to `${ENERGYIQ_API_ORIGIN}/api/:path*`. The rewrite destination is bound when `next build` runs (Next.js writes it into the routes manifest), so the same `ENERGYIQ_API_ORIGIN` value must be set at build and at `next start`; the README says so. The variable and its dev default `http://127.0.0.1:8000` (used when `NODE_ENV` is not `production`) are read only in `next.config.ts` and `src/lib/api/server.ts`, never in a module the browser loads. A production build without it fails with a message naming the variable. No `NEXT_PUBLIC_` variable exists, and a test asserts the built client bundle (`.next/static`) does not contain the literal `127.0.0.1:8000`. In the browser, every API call uses a relative `/api/v1/...` path.
- **AC-3**: Generated client. `pnpm gen:api` runs Orval against `../backend/tests/snapshots/openapi.json` with `client: "react-query"`, `httpClient: "fetch"`, the HTTP response envelope turned off (generated functions resolve to the response body, not `{data, status, headers}`), `mode: "tags-split"`, output in `frontend/src/lib/api/generated/` (models in `generated/model/`), and every call routed through the custom mutator in `fetcher.ts`, whose second parameter type (`RequestOptions`) the generated functions accept per call. A type level test proves the generated `me` function resolves to `UserOut` and its query hook's `data` is `UserOut | undefined`. The output is committed and deterministic: a test regenerates it into a temporary directory and fails on any difference. The backend emits each `operationId` as the route function name (for example `login`, `list_properties`) through FastAPI `generate_unique_id_function`; a backend test enumerates every operation in the generated OpenAPI document (all 25) and proves the ids are unique, and the snapshot is updated in the same change. The `health` tag file contains both `/health` and `/health/ready`. Decimal fields stay typed `string`; no generated or hand written code converts kWh or money strings to `number`.
- **AC-4**: Mutator. `frontend/src/lib/api/fetcher.ts` is the only place that performs API `fetch` calls. It chooses its mode by `typeof window`: in the browser it uses relative URLs with `credentials: "same-origin"`; on the server it requires the `baseUrl`, cookie, and `cache` that `serverRequestInit()` supplies, and throws a programming error (`ServerFetchWithoutInitError`) if called on the server without them, so a client component query that runs during server rendering without a prefetch fails loudly in development instead of sending an anonymous request. It sends `X-EnergyIQ-CSRF: 1` on POST, PUT, PATCH, and DELETE and never on GET or HEAD; sends `Content-Type: application/json` when a body exists; passes through a caller supplied `Idempotency-Key` in `RequestOptions.headers` (the generated client has no typed idempotency parameter, and the mutator adds no idempotency option of its own); returns `undefined` for 204; throws `ApiError` for any response whose content type starts with `application/problem+json`, carrying `status`, `code`, `title`, `detail`, `requestId` (body `request_id`, else the `X-Request-ID` response header), `errors` (the `{loc, code, message}` list), and `retryAfterSeconds` (from an integer `Retry-After`, else `null`); throws `ApiUnavailableError` (carrying `requestId` when known) for a network failure, a timeout, any response that is neither 2xx nor a problem body (for example the bare 500 the Next.js rewrite returns when FastAPI is down, or an HTML 404), a 2xx whose JSON body cannot be parsed, or a 503 problem with code `database_unavailable` or `schema_out_of_date`. Server side fetches carry `AbortSignal.timeout(10_000)`.
- **AC-5**: Server reads. `frontend/src/lib/api/server.ts` imports `server-only` and exports `serverRequestInit()` and `getServerQueryClient()`. `serverRequestInit()` returns the `baseUrl` (`ENERGYIQ_API_ORIGIN`), a `Cookie` header with only the `energyiq_session` and `__Host-energyiq_session` cookies from the incoming request (the name in use depends on `ENERGYIQ_SESSION_COOKIE_SECURE`), and `cache: "no-store"`. No authenticated response is ever stored in the Next.js data cache or shared across requests. `getServerQueryClient()` is wrapped in `React.cache`, so one server request gets exactly one QueryClient and different requests never share one; the browser creates its single client once in the provider's `useState`. The signed in home page reads `/api/v1/auth/me` through that request's QueryClient (`fetchQuery` with the generated query options, so the query key matches the client hook) and hands it over with `HydrationBoundary`. First load shows the email with no browser request for it and exactly one `/auth/me` call on the server per request.
- **AC-6**: Session guard. Every page in the `(app)` route group starts with `await requireSession(path, searchParams)`, where `path` is the page's own route and `searchParams` comes from the page props (a layout cannot see the URL, and it is not rerendered when the user moves between pages under it, so the layout is not the guard). `requireSession` fetches `/api/v1/auth/me` through `getServerQueryClient()` (one call per request however many server components ask). On 401 `not_authenticated` it calls `redirect("/login?next=" + encoded path and query)`; `redirect()` throws a special Next.js error, so `requireSession` never wraps it in a `try` that could swallow it. The `(auth)` pages (`/login`, `/register`) call `redirectIfSignedIn()`, which sends a signed in visitor to `/`. A session revoked or expired on the backend is refused on the next server rendered page, and on the next browser API call through AC-10 (the backstop for movement between already loaded pages). An `ApiUnavailableError` here renders the unavailable panel from AC-12, never a redirect to login.
- **AC-7**: Login. `/login` shows email and password fields. The server page reads `next` from its `searchParams` and passes the `safeNextPath` result (AC-11) to the form; success goes there. A 401 `invalid_credentials` shows one form level message, "Email or password is incorrect.", attached to neither field. A 429 `too_many_attempts` shows "Too many attempts. Try again in N minutes." with N being `retryAfterSeconds` rounded up to whole minutes, at least 1, using "1 minute" for one; with no usable `Retry-After` it shows "Too many attempts. Try again later." A 422 maps each error to an input by stripping the leading `"body"` from `loc` and matching the next element (`email` or `password`), and shows copy from `en.ts` keyed by the error `code` (for example `invalid_email`, `password_length`), with a generic "This value is not valid." for unknown codes; the server's `message` text is never shown. Errors it cannot map go to the form level alert. Login may show `password_length` for a short password; that is accepted, since the backend already reveals the policy. Every other `ApiError` shows the shared fallback from AC-12.
- **AC-8**: Register. `/register` shows email and password fields, with a client side hint that the password must be 12 to 128 characters counted after NFKC normalization (`[...value.normalize("NFKC")].length`). The hint advises only; it never blocks submit, and the server's 422 is the authority. The client sends the email as typed (the server normalizes it). A 201 signs the user in (the backend sets the session cookie) and goes to `/`. A 409 `email_taken` shows "An account with this email already exists." on the email field, with a link to `/login`. 422, 429, and other errors are handled as in AC-7.
- **AC-9**: Logout. A sign out control on the home page POSTs `/api/v1/auth/logout` with the CSRF header. On 204 it clears the browser QueryClient and does a full page navigation (`window.location.assign("/login")`), so no in memory or router cached state survives. On 403 `csrf_rejected` or `ApiUnavailableError`, it shows an inline alert and stays signed in; it never pretends the session ended.
- **AC-10**: Session lost mid use. A global `onError` on the browser QueryClient's query cache and mutation cache reacts only to `ApiError` with status 401 and code `not_authenticated`. Login's 401 is `invalid_credentials`, so it is excluded by code, not by operation name. A once only flag makes parallel 401s cause a single navigation: clear the QueryClient, then `window.location.assign("/login?next=" + encoded current path and query)`.
- **AC-11**: Safe redirect. `safeNextPath(value)` percent decodes the value up to twice (stopping when it no longer changes), then returns the original value only when the decoded form starts with exactly one `/`, the next character is not `/` or `\`, it contains no control characters or backslashes, it has no scheme, and its path is not `/api` or anything under `/api/`, `/login`, or `/register` (including a trailing slash, a query, or a hash). Otherwise it returns `/`. A table test covers `//evil.example`, `/\evil.example`, `/%5Cevil.example`, `https://evil.example`, `/%2F%2Fevil.example`, `/%252F%252Fevil.example`, `javascript:alert(1)`, an empty string, `/login`, `/login/`, `/login?x=1`, `/register#a`, `/api/v1/auth/logout`, and a valid `/properties?x=1`.
- **AC-12**: Errors shown to the user. `requireSession` and every server prefetch catch `ApiUnavailableError` themselves and render the server component `<ApiUnavailable requestId>`: "EnergyIQ can't reach its server right now.", "Reference: <requestId>" when known, and a Retry button that calls `router.refresh()` inside `startTransition` (in production Next.js hides the error class and its fields from `error.tsx`, and `reset()` alone does not rerun a server render). `error.tsx` handles every other unexpected error with "Something went wrong. Try again." and the error `digest` as its reference, with a Retry that refreshes and then resets. A browser mutation that hits `ApiUnavailableError` shows the unavailable message as an inline form alert. A 403 `csrf_rejected` shows "This page was opened from an address EnergyIQ does not trust. Open http://localhost:3000 and try again." in development, and a generic security message in production. Any other `ApiError` shows "Something went wrong. Reference: <requestId>." No stack trace, raw response body, server `message` text, or blank page ever reaches the user.
- **AC-13**: Security and cache headers. Every Next.js response carries `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `X-Frame-Options: DENY`, `Content-Security-Policy: frame-ancestors 'none'`, and `Permissions-Policy: camera=(), microphone=(), geolocation=()`. `X-Powered-By` is absent (`poweredByHeader: false`). Protected pages and the auth pages send `Cache-Control: no-store`, so after logout the browser's back button cannot show a stored signed in page. The backend adds `Cache-Control: no-store` to every `/api/v1/auth/*` response (a backend test checks all four).
- **AC-14**: Client address behind the proxy. The backend adds setting `ENERGYIQ_FORWARDED_ALLOW_IPS`, a JSON list of IP addresses or CIDR ranges (not hostnames, which Uvicorn cannot match), like `ENERGYIQ_TRUSTED_ORIGINS`. Defaults: `["127.0.0.1", "::1"]` in `dev` and `test`. In `prod` there is no default: startup fails unless it is set explicitly, and `[]` is allowed but must be deliberate, so the shared bucket problem can never ship silently. `create_app` adds Uvicorn's `ProxyHeadersMiddleware` with those addresses as the outermost middleware (it runs before the request context, CSRF, and access log). IPv4 mapped IPv6 peers (`::ffff:127.0.0.1`) are normalized to IPv4 before matching. The login and register rate limit key then uses the forwarded client: the rightmost `X-Forwarded-For` entry that is not a trusted proxy, and only when the direct peer is trusted. Tests drive the ASGI app with explicit client addresses (the test client's own peer is the string `"testclient"`, not an IP) and prove: an untrusted peer's `X-Forwarded-For` is ignored; a trusted peer forwarding `"<spoofed>, <real>"` yields `<real>`; two different forwarded addresses get separate rate limit buckets; an IPv4 mapped trusted peer is trusted; and a trusted peer sending junk or comma separated `X-Forwarded-Proto` (such as `https,http`) cannot make the CSRF `Origin` check pass or fail wrongly. The documented Uvicorn command adds `--no-proxy-headers`, so the app setting is the only source of truth. The backend half of this criterion is built and tested. Its live check was run on 2026-11-05 against Next.js 16.4.5, both `next dev` and `next build` plus `next start`, and failed: the `/api` rewrite adds no `X-Forwarded-For` at all, and it passes a header the browser sent through unchanged, so a browser could pick its own rate limit bucket. The Next.js half is now AC-18.
- **AC-15**: Accessibility of the auth forms. ESLint includes the Next.js core web vitals and `jsx-a11y` rules with zero warnings. On `/login` and `/register`: every input has a visible label; field errors are linked through `aria-describedby` and set `aria-invalid`; the form level alert uses `role="alert"`; on a failed submit, focus moves to the first invalid field (or to the alert when no field is invalid); the submit button shows a pending state and blocks double submit. `vitest-axe` reports zero violations for each form in its idle, field error, and form error states.
- **AC-16**: Copy and time. Every user facing string lives in `frontend/src/messages/en.ts`. Dates and times shown to users go through one formatter, `formatDateTime`, using `America/Santo_Domingo`. The home page shows "Signed in as <email>" and "Member since <date>" from `UserOut.created_at`, which the backend sends as an ISO 8601 UTC string. A test proves `2026-11-05T02:30:00Z` formats as November 4, 2026 (Santo Domingo is UTC−4). An unparseable value renders nothing for that line, never "Invalid Date", and a test covers it.
- **AC-17**: Docs. The README documents the local run: PostgreSQL through Compose, Uvicorn with `--no-proxy-headers`, then `pnpm dev`. It says to open exactly `http://localhost:3000` (the dev trusted origin; `127.0.0.1:3000` fails the CSRF `Origin` check), and that `ENERGYIQ_API_ORIGIN` must match at build and start. `docs/03-TECH-STACK.md` lists the frontend packages with their pinned versions. ADR-008 records the frontend data access pattern, including the multi hop proxy rule: every proxy that appears to the right of the browser address in `X-Forwarded-For`, and the Next.js host itself, must be listed in `ENERGYIQ_FORWARDED_ALLOW_IPS`, or every user maps to that proxy's address. It also records the AC-18 decision: why Next.js cannot produce the address alone, the `ENERGYIQ_EDGE_PROXY` flag, and that `true` is only safe behind an edge proxy that appends the real peer. The README documents `ENERGYIQ_EDGE_PROXY` next to `ENERGYIQ_API_ORIGIN`. `docs/PROGRESS.md` and the roadmap are updated with the checks actually run.
- **AC-18**: Client address from Next.js to FastAPI. Finding behind it (2026-11-05, Next.js 16.4.5): the rewrite never sets `X-Forwarded-For`; it keeps a browser supplied value as is; and Next.js fills the header from the socket address only when the browser sent none, and only on requests that pass through a `proxy.ts`. Because the socket address is lost once a browser sends the header, Next.js cannot repair a spoofed value itself. The fix is `frontend/src/proxy.ts` (the Next.js 16 name for middleware), with matcher `/api/:path*` and no other job, controlled by the server only setting `ENERGYIQ_EDGE_PROXY`, which is exactly `true` or `false`:
  - `experimental.caseSensitiveRoutes` must stay `true`, and every rewrite to FastAPI must match a path covered by `proxy.ts`. Otherwise a case variant such as `/API/` could bypass header removal. Rerun `frontend/scripts/check-edge-proxy.mjs` after a Next.js upgrade or rewrite change.
  - `false`: `proxy.ts` deletes `X-Forwarded-For` and `X-Forwarded-Proto` from the request before the rewrite forwards them. FastAPI then sees only the Next.js peer and its own scheme, nothing can be spoofed, and every browser shares one login and register bucket. This is the development default and the safe state.
  - `true`: `proxy.ts` leaves the header alone. Use it only when a trusted edge proxy (a load balancer, nginx, or Caddy) sits in front of Next.js, appends the real peer address to `X-Forwarded-For`, overwrites (never appends to) `X-Forwarded-Proto` with the browser scheme, and is the only way to reach Next.js. FastAPI's existing rightmost untrusted rule (AC-14) then picks the address the edge appended and ignores anything a browser put before it.
  - Unset or any other value: in development and test it behaves as `false`. `next build` and `next start` throw an error naming `ENERGYIQ_EDGE_PROXY`, the same way `ENERGYIQ_API_ORIGIN` does, so a production deploy cannot choose by accident. `proxy.ts` itself treats anything other than the exact text `true` as `false`.
  - The value is read when a request arrives, not baked into the build, so one build serves both topologies. `/develop` proves this by running `next start` with each value without rebuilding.
  - Server Components that call FastAPI directly send no `X-Forwarded-For`; the only rate limited routes (login and register) are browser calls through the rewrite, so nothing else depends on it.
  - Tests: a unit test calls `proxy` with a `NextRequest` for each case (`false` removes a supplied header, `false` with no header, `true` keeps a supplied header, `true` with no header, unset in `dev`) and checks the matcher covers `/api/v1/auth/login` but not `/login`. A live check puts an echo server in place of FastAPI and shows what arrives: with `false`, a plain request and one with `X-Forwarded-For: 6.6.6.6` both arrive with no header; with `true`, `6.6.6.6` arrives as sent and a plain request arrives with the socket address. If a later Next.js release changes this behavior, that live check is the tripwire.

## Decision

**Chosen option**: Orval generated React Query client through one mutator, server prefetch with hydration, and a server layout session guard over the ADR-007 same origin proxy.

The browser talks only to Next.js; Server Components read FastAPI directly with the forwarded session cookie; one mutator and one server helper own every cross cutting rule.

**Implementation skills**: `orval` (`orval-labs/orval`, `.claude/skills/orval/`) · `tanstack-query` (`tanstack-skills/tanstack-skills`, `.claude/skills/tanstack-query/`) · `next-dev-loop` (`vercel/next.js`, `.claude/skills/next-dev-loop/`) · `tailwind-4-docs` (`lombiq/tailwind-agent-skills`, `.claude/skills/tailwind-4-docs/`) · `shadcn` (installed globally) · `vitest` (`antfu/skills`, `.claude/skills/vitest/`) · `msw` (`pproenca/dot-skills`, `.claude/skills/msw/`) · `vercel-react-best-practices` (installed globally) · `fastapi` (`.claude/skills/fastapi/`, for the AC-3 and AC-14 backend changes)

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

**Data model sketch**: No database change. The frontend stores nothing; the session lives in the backend `sessions` table (spec 0009/0002). Client side state is limited to the React Query cache, which is per request on the server and cleared on logout or a lost session in the browser.

**State transitions** (browser session as the UI sees it):
`unknown` (server render starts) → `signed_in` (`/auth/me` 200) or `signed_out` (401) or `unavailable` (`ApiUnavailableError`).
`signed_out` → `signed_in` on login or register success.
`signed_in` → `signed_out` on logout 204, or on a `not_authenticated` 401 mid use (AC-10).
`unavailable` → the state is resolved again on Retry.

**Frontend layout** (target):
```text
frontend/
  next.config.ts            rewrites, headers, poweredByHeader false, env check
  orval.config.ts
  src/app/
    layout.tsx              root, QueryProvider (browser client in useState)
    error.tsx               unexpected errors only (AC-12)
    (auth)/login/page.tsx   redirectIfSignedIn, reads next from searchParams
    (auth)/register/page.tsx
    (app)/layout.tsx        chrome only, not the guard
    (app)/page.tsx          home: requireSession("/"), HydrationBoundary
  src/components/ui/        shadcn components (owned source)
  src/components/auth/      LoginForm, RegisterForm, SignOutButton
  src/components/ApiUnavailable.tsx   server panel + Retry (router.refresh)
  src/lib/api/fetcher.ts    the mutator (only fetch caller), RequestOptions
  src/lib/api/errors.ts     ApiError, ApiUnavailableError, toApiError
  src/lib/api/server.ts     server-only: serverRequestInit, getServerQueryClient,
                            requireSession, redirectIfSignedIn
  src/lib/api/query-client.ts   browser client factory, 401 latch, retry rules
  src/lib/api/generated/    Orval output, committed
  src/lib/safe-next.ts
  src/lib/format.ts         formatDateTime (America/Santo_Domingo)
  src/messages/en.ts
  tests/                    Vitest, MSW handlers, axe checks
```

**API surface** (existing backend routes this ticket consumes; no new endpoints):
| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors the UI handles |
|---|---|---|---|---|---|
| `/api/v1/auth/register` | POST | `email: string` (req), `password: string` (req) | 201 `UserOut`, session cookie | public, CSRF header | 409 `email_taken`, 422 `validation_error`, 429 `too_many_attempts` |
| `/api/v1/auth/login` | POST | `email`, `password` (req) | 200 `UserOut`, session cookie | public, CSRF header | 401 `invalid_credentials`, 422, 429 |
| `/api/v1/auth/me` | GET | session cookie | 200 `UserOut {id, email, created_at}` | session | 401 `not_authenticated`, 503 |
| `/api/v1/auth/logout` | POST | session cookie | 204 always (with or without a session), cookie cleared | CSRF header | 403 `csrf_rejected`, 503 |

All four also share 403 `csrf_rejected` on unsafe methods and 503 `database_unavailable`. Field errors are `{loc, code, message}` with `loc` starting at `"body"`.

Backend changes in this ticket: readable `operationId` values (AC-3), `Cache-Control: no-store` on auth responses (AC-13), the forwarded address middleware with its setting (AC-14), and, on the Next.js side, `proxy.ts` with `ENERGYIQ_EDGE_PROXY` (AC-18).

**Value sourcing**:
| Action | Value produced / displayed | Source |
|---|---|---|
| Rewrite (bound at build) and server fetch (read at runtime) | Backend origin | `ENERGYIQ_API_ORIGIN`, same value at build and start, dev default `http://127.0.0.1:8000`, read only in `next.config.ts` and `server.ts` |
| Session guard redirect | Requested path and query | The page's own route constant plus its `searchParams` prop |
| Field error copy | Message per field | `en.ts` keyed by error `code`, generic fallback |
| CSRF failure copy | Which address to open | `en.ts`; dev text names `http://localhost:3000` |
| Every unsafe browser call | `X-EnergyIQ-CSRF: 1` | Constant in the mutator, required by ADR-007 |
| Server reads | Session cookie | Incoming request cookies via `next/headers`, filtered to the two names from ADR-007 |
| Backend `Origin` check | Browser origin | The browser `Origin` header, passed through the rewrite; must equal a `ENERGYIQ_TRUSTED_ORIGINS` entry (dev default `http://localhost:3000`) |
| Rate limit key | Client address | Rightmost untrusted `X-Forwarded-For` entry, honored only from `ENERGYIQ_FORWARDED_ALLOW_IPS` peers (AC-14). Next.js sends the header only when `ENERGYIQ_EDGE_PROXY=true`, and then it is the address a trusted edge proxy appended; with `false` there is no header and the key is the Next.js peer (AC-18) |
| Whether Next.js forwards the client address | `true` or `false` | `ENERGYIQ_EDGE_PROXY`, read per request in `proxy.ts`, required in production builds and starts, `false` in dev and test |
| Login and register errors | Error code, field errors | Problem body `code` and `errors[].loc` / `msg` |
| 429 message | Minutes to wait | `Retry-After` response header (seconds), rounded up |
| Unavailable and fallback reference | Request id | Problem body `request_id`, else the `X-Request-ID` response header; absent when the network failed. `error.tsx` shows the error `digest` instead |
| Home page | Email, member since | `UserOut.email`, `UserOut.created_at` formatted in `America/Santo_Domingo` |
| Post login target | Destination path | `next` query parameter after `safeNextPath`, else `/` |
| Idempotent POSTs (P3-02 on) | `Idempotency-Key` | The form creates one `crypto.randomUUID()` per submission and reuses it if that same submission is retried; it passes the header through `RequestOptions.headers`, since the generated function has no typed idempotency parameter |
| Generated types | Request and response shapes | `backend/tests/snapshots/openapi.json` |

**Key invariants**:
- The browser never holds a readable credential: no token in JavaScript, storage, or URLs; the cookie stays HttpOnly.
- No authenticated response is cached across requests or users: `cache: "no-store"` on server fetches, one `React.cache` scoped QueryClient per server request, `Cache-Control: no-store` on auth responses and protected pages.
- `fetcher.ts` is the only API `fetch` caller; `server.ts` is the only reader of incoming cookies and of `ENERGYIQ_API_ORIGIN` at runtime.
- Every `(app)` page calls `requireSession` first; a layout is never the guard.
- `redirect()` is never caught.
- No `NEXT_PUBLIC_` variable, and no backend origin in the client bundle.
- Server `message` text from problem bodies is never shown; copy comes from `en.ts`.
- kWh and money values stay strings end to end in P3-01; any later arithmetic needs an exact decimal approach, never `Number`.
- A redirect target is always a validated same origin relative path.
- The generated client always matches the committed snapshot (drift test).

**Security model**: Every page except `/login` and `/register` requires a valid backend session, checked on the server on every navigation. Ownership and tenant checks stay in the backend (Phase 2); the frontend never filters data for authorization. CSRF follows ADR-007 (header plus `Origin`). Clickjacking is blocked by `frame-ancestors 'none'` and `X-Frame-Options`. Login and register keep per client rate limits only when a trusted edge proxy supplies the address (`ENERGYIQ_EDGE_PROXY=true`); otherwise the browser header is dropped and the limits fall back to one shared bucket, which is safe but coarse. The per email lockout does not depend on the address in either case. No personal data beyond the user's own email is shown, and nothing is logged in the browser. A full nonce based Content Security Policy is deferred to P8.

**Configuration required**:
- `ENERGYIQ_API_ORIGIN` (frontend, server only): FastAPI origin for the rewrite and server reads. Dev default `http://127.0.0.1:8000`; required for a production build.
- `ENERGYIQ_FORWARDED_ALLOW_IPS` (backend): JSON list of IPs or CIDR ranges whose `X-Forwarded-For` is trusted. Default `["127.0.0.1", "::1"]` in `dev` and `test`; required in `prod` (startup fails if unset; set it to the Next.js host address and every proxy in front of it).
- `ENERGYIQ_EDGE_PROXY` (frontend, server only): exactly `true` or `false`. `true` means a trusted edge proxy in front of Next.js appends the real peer to `X-Forwarded-For`, overwrites `X-Forwarded-Proto`, and is the only route to Next.js; `false` drops both headers. Default `false` in dev and test; required in production (`next build` and `next start` fail naming it). Never prefix it with `NEXT_PUBLIC_`.
- Existing `ENERGYIQ_TRUSTED_ORIGINS` must include the browser origin of the Next.js app (dev default `http://localhost:3000` already does).

**Critical test scenarios**:
- Happy path: register, land on home with "Signed in as", sign out, sign in again with `next=/`, all through the rewrite on live servers, verifies **AC-2**, **AC-5**, **AC-7**, **AC-8**, **AC-9**.
- Mutator contract with MSW: CSRF header only on unsafe methods; problem body (including `application/problem+json; charset=utf-8`) to `ApiError` with `retryAfterSeconds`; a bare text 500, an HTML 404, an unparseable 2xx, a timeout, and a network error to `ApiUnavailableError`; 204 to `undefined`; a server side call without `serverRequestInit` throws `ServerFetchWithoutInitError`, verifies **AC-4**.
- Cookie isolation: `serverRequestInit` forwards only the two session cookies, sets `no-store`, and two simulated requests never share a QueryClient; one request makes one `/auth/me` call even with guard plus prefetch, verifies **AC-5**.
- Auth/permission: no cookie, or a revoked session, on `/` redirects to `/login?next=%2F`; a `not_authenticated` 401 on a browser query mid use clears the cache and navigates once even when three queries fail together; an `invalid_credentials` 401 does not, verifies **AC-6**, **AC-10**.
- Failure case: FastAPI stopped; `/` renders the unavailable panel with Retry, not a login redirect; logout shows an inline alert and the session survives; restarting FastAPI and pressing Retry recovers, verifies **AC-6**, **AC-9**, **AC-12**.
- Field error mapping: `["body", "password"]` with `password_length` lands on the password input with `en.ts` copy; an unknown code uses the fallback; server `message` never renders, verifies **AC-7**, **AC-8**.
- Back after logout shows no signed in content (`no-store`), verifies **AC-13**.
- Open redirect table for `safeNextPath`, verifies **AC-11**.
- Spoofed `X-Forwarded-For` from an untrusted peer is ignored; a trusted proxy chain yields the rightmost untrusted address; two addresses have separate buckets; an IPv4 mapped peer is trusted; junk `X-Forwarded-Proto` cannot break the `Origin` check; `prod` without the setting fails at startup, verifies **AC-14**.
- `proxy.ts` unit cases and the echo server live check for both `ENERGYIQ_EDGE_PROXY` values (a spoofed header is dropped with `false`, an appended chain survives with `true`), plus a production start with the variable unset that fails naming it, verifies **AC-18**.
- End to end with `true`: `X-Forwarded-For: 198.51.100.77` sent through `:3000` to a real FastAPI stores `client_key = HMAC(secret, "198.51.100.77")`; the same request with `false` stores the key of `127.0.0.1`, verifies **AC-14**, **AC-18**.
- axe on both forms in three states, plus focus on first invalid field, verifies **AC-15**.
- Santo Domingo date across the UTC midnight boundary, verifies **AC-16**.
- Codegen drift test and backend `operationId` uniqueness test, verifies **AC-3**.

## Build plan

Ordered as thin end to end slices (no build approach recorded; Tracer Bullet assumed). The first slice proves the whole thread (browser, rewrite, cookie, FastAPI, server guard) before any polish.

1. Backend: readable `operationId` from route function names, uniqueness test over all 25 operations, `Cache-Control: no-store` on auth responses, regenerate the OpenAPI snapshot, satisfies **AC-3**, **AC-13**.
2. Backend: `ENERGYIQ_FORWARDED_ALLOW_IPS` setting with the `prod` required rule, outermost `ProxyHeadersMiddleware` with IPv4 mapped normalization, the address and forwarded proto tests with explicit ASGI client addresses, `--no-proxy-headers` in the documented command, satisfies **AC-14**.
3. Scaffold `frontend/` (verify current stable versions first, then pin): Next.js App Router, strict TypeScript, pnpm, Tailwind CSS v4, shadcn init, ESLint with jsx-a11y, Prettier, Vitest with Testing Library and MSW, the scripts from AC-1, satisfies **AC-1**.
4. `next.config.ts`: rewrite, `ENERGYIQ_API_ORIGIN` handling with the production failure, security headers, `poweredByHeader: false`, satisfies **AC-2**, **AC-13**.
4a. `src/proxy.ts` and the `ENERGYIQ_EDGE_PROXY` production check in `next.config.ts`, with the unit tests and the echo server live check from AC-18 (keep the echo script in the repo so it can be rerun), satisfies **AC-18**.
5. Orval config (`react-query` client, `fetch` http client with the envelope off, `tags-split`, custom mutator and its `RequestOptions` type), commit the generated output, add the drift test and the `me` type level test, satisfies **AC-3**.
6. Tracer slice: `errors.ts` and `fetcher.ts` with MSW contract tests; `server.ts` (`serverRequestInit`, `getServerQueryClient`, `requireSession`); browser query client and provider; home page with `requireSession("/")`, `fetchQuery`, and hydration; a minimal login form; prove sign in to home on live servers, plus the end to end address check against a real FastAPI with `ENERGYIQ_EDGE_PROXY=true` and then `false` (AC-18), satisfies **AC-4**, **AC-5**, **AC-6**, **AC-14**, **AC-18**.
7. Thicken auth: full login and register forms (react-hook-form with Zod through shadcn Form, hints never blocking submit), field error mapping by `code`, 429 copy, `safeNextPath` with its table test, `redirectIfSignedIn`, satisfies **AC-7**, **AC-8**, **AC-11**.
8. Sign out and the lost session handling (global cache `onError`, once only latch, full page navigation), satisfies **AC-9**, **AC-10**.
9. `ApiUnavailable` panel with `router.refresh` Retry, `error.tsx` for unexpected errors, `csrf_rejected` and fallback copy, inline mutation alerts, `no-store` on pages; test with FastAPI stopped and restarted, satisfies **AC-12**, **AC-13**.
10. Messages module, `formatDateTime`, the "Member since" line and its boundary test, satisfies **AC-16**.
11. Accessibility pass on the auth forms: focus management, aria wiring, the axe tests in all three states, satisfies **AC-15**.
12. Docs: README run steps, tech stack pins, ADR-008, roadmap and progress with the checks actually run; full backend suite (`ENERGYIQ_REQUIRE_DB=1 uv run pytest`, Ruff, Pyright) and all frontend scripts, satisfies **AC-1**, **AC-17**.

## Consequences

**Positive**:
- P3-02 to P3-04 add screens without touching CSRF, cookies, base URLs, or error mapping.
- API changes surface as typed compile errors and reviewable generated diffs.
- First loads render without spinners; revoked sessions are caught on every server rendered page and on the first browser API call after that.
- The proxy no longer collapses login rate limits into one global bucket.

**Negative / tradeoffs**:
- Large generated diffs whenever the API changes; reviewers need to skim them.
- Two runtimes for the same client code (server and browser) add a class of bugs; the per request QueryClient and `no-store` rules must hold forever.
- Every server rendered protected page costs one `/auth/me` call.
- Every new `(app)` page must remember to call `requireSession`; a test in P3-02 should enumerate `(app)` pages and check it.
- Unsaved form input is lost when a session ends mid use.
- The rewrite target is fixed at build time, so changing the backend address needs a rebuild.
- Backend changes ride along in a frontend ticket, and production now refuses to start until `ENERGYIQ_FORWARDED_ALLOW_IPS` is set, and the Next.js build and start refuse until `ENERGYIQ_EDGE_PROXY` is set.
- Until an edge proxy exists (P8), development and any direct deployment share one login and register rate limit bucket. That is the cost of not being spoofable; the per email lockout still applies.
- Per address limits rely on one Next.js behavior (it fills `X-Forwarded-For` from the socket when the header is absent), which is undocumented in this form; the live check guards it, and losing it degrades to the shared bucket, never to a spoofable one.
- Two process local development (Uvicorn and `pnpm dev`) with no single start command yet.
- English only until a localization ticket exists.

**Neutral**:
- The OpenAPI snapshot changes once for the new operation ids.
- A Node.js toolchain joins `uv`; P8 continuous integration must run both.
- The `/docs` ignore rule means this spec needs force staging, as earlier specs did.

## Follow-up

- [ ] Frontend conventions (the mutator only rule, `server.ts` as sole cookie reader, `no-store`, the messages module, the installed frontend skills) are not yet in any `AGENTS.md`. They belong in a nested `frontend/AGENTS.md`, with a one line pointer from root `AGENTS.md`.
- [ ] Root `AGENTS.md` has no `## Agent skills` section. It should list the skills installed on 2026-11-04 (`orval`, `tanstack-query`, `next-dev-loop`, `tailwind-4-docs`, `vitest`, `msw`) and record the declines: Next.js DevTools MCP declined; the react-hook-form plus Zod skill was chosen but no longer exists in `jezweb/claude-skills` (`pnpm` skill not chosen).
- [ ] Consider a react-hook-form or Zod skill from another publisher (for example `pproenca/dot-skills`), since the chosen one could not be installed.
- [ ] P8: a nonce based Content Security Policy, and the real `ENERGYIQ_FORWARDED_ALLOW_IPS` and `ENERGYIQ_EDGE_PROXY` values for the deployed topology (the edge must append the real peer, overwrite `X-Forwarded-Proto`, and be the only route to Next.js; a network rule enforces that).
- [x] P3-03: Recharts 3.10.1 draws the chart, and `src/lib/decimal.ts` formats kWh strings with scaled `BigInt` and half even rounding (spec 0011 child 0002).
- [ ] Localization (Spanish) as its own ticket when product calls for it.
