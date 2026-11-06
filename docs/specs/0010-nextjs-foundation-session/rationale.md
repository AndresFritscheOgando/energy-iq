# 0010. Rationale: Next.js foundation, typed API layer, and browser session

Decision record for [index.md](index.md). `/develop` builds from the index; this file holds the why.

## Context

Phase 2 closed on 2026-11-04 with an owner isolated REST API: 25 operations in `backend/tests/snapshots/openapi.json`, cookie sessions, CSRF by header plus `Origin`, problem details errors (RFC 9457 bodies with a stable `code`), request ids, and idempotent POSTs. Phase 3 puts a browser product on top of it. P3-01 is the foundation every later Phase 3 ticket stands on: P3-02 (property selector, meter creation, readings form), P3-03 (consumption chart with gap states), and P3-04 (accessibility and end to end demo). Whatever P3-01 sets up (where data is fetched, how types reach the UI, how the session travels, how errors look) is copied by every screen after it.

ADR-007 already fixed the session itself: an opaque token in an HttpOnly `SameSite=Lax` cookie, `X-EnergyIQ-CSRF: 1` on unsafe requests, CORS kept credential free, and a Next.js rewrite of `/api` so the browser sees one origin. It left the client side open: how server rendered pages carry the cookie, how a page knows the user is signed in, how a revoked session is noticed, and what the user sees when the API is down. ADR-004 fixed Next.js, TypeScript, and the App Router. The tech stack document leaves the UI libraries to this phase, and the version policy requires exact tested pins.

Three forces shape the problem. **Trust:** the browser must never hold a readable credential, a server render must never serve one user's data to another (Next.js caches `fetch` results unless told not to), and redirects after login must not become an open redirect. **Contract drift:** the backend already treats the OpenAPI snapshot as a reviewed contract, and Decimal values travel as JSON strings. A UI that retypes those shapes by hand drifts silently and is tempted to turn kWh strings into binary floats. **Hidden coupling in the proxy:** the backend keys login and register rate limits by `request.client.host`. Behind a same origin proxy every browser arrives from the Next.js server address, so the per address limit quietly becomes one global bucket, and one attacker could lock every user out of login.

If nothing is decided, P3-02 would invent a fetch pattern per screen, the CSRF header would be added by hand in some places and forgotten in others, and the rate limit regression would ship unnoticed.

Workspace: a new `frontend/` directory beside `backend/` in the same repository (not a JavaScript monorepo with workspaces; the two halves share only the OpenAPI snapshot file). No build approach is recorded in `AGENTS.md` or a scope header, so the build plan assumes the default: thin end to end slices (Tracer Bullet).

## Options considered

### Typed API layer

**Option A: Orval with React Query hooks and one fetch mutator (chosen).** Orval reads the snapshot and generates a request function plus `useQuery` and `useMutation` hooks per operation, all routed through one hand written function (the mutator) that owns base URL, CSRF, cookies, and error mapping.
Pros: one call site per operation for both server and browser; hooks give mutation state and cache invalidation that P3-02 forms need; the mutator puts every cross cutting rule in one tested file. Cons: the most generated code of the options to review in diffs; adds TanStack Query as a runtime dependency; operation names follow `operationId`, so the backend must emit readable ids.

**Option B: openapi-typescript plus openapi-fetch.** Generate only types; call a small typed fetch wrapper by path.
Pros: no generated runtime code, tiny bundle, path based calls read like the API docs. Cons: no hooks, so mutation state and cache invalidation are written by hand per form; calling by path string is less discoverable than named functions.

**Option C: Hey API (`@hey-api/openapi-ts`).** Generates an SDK with plugins for Zod and TanStack.
Pros: modern plugin model, optional runtime validators. Cons: younger and faster moving configuration surface; overlaps Orval's strengths without a clear win for this API.

**Option D: Handwritten types.** Pros: zero tooling. Cons: drifts from the contract with no signal; rejected.

The engineer chose Orval with React Query hooks. My first suggestion was Option B on the grounds of the least generated code. Orval is a sound choice here: it is mature, its mutator hook gives the same single choke point, and the engineer also wants client side caching for P3-02 and P3-03, which Option B would make them build by hand. The cost they accept is a larger generated diff, which the committed output and drift test make reviewable rather than hidden.

### Where data is fetched

**Server prefetch plus hydration (chosen).** Server Components call the generated functions with the forwarded cookie, fill a per request QueryClient, and hand it to the browser through `HydrationBoundary`. Client components then read the same queries with the hooks, so there is no spinner on first load, and mutations invalidate queries.
Pros: fast first paint, one cache, the documented TanStack pattern for the App Router. Cons: two execution contexts for the same function (server needs an absolute URL and an explicit cookie, the browser needs neither); per request QueryClient discipline is mandatory, or data leaks between users.

**Server reads as props, hooks only in client islands.** Pros: simpler data path for read only pages. Cons: two read paths to keep consistent once a page both reads and mutates.

**Browser only.** Pros: one context, simplest mental model. Cons: a loading state and a request waterfall on every page; the session guard still has to run on the server.

### Session guard

**Server side `/api/v1/auth/me` check (chosen).** The engineer picked "the server layout calls `/auth/me`". The cross check showed a layout cannot be the guard: App Router layouts receive no pathname (so they cannot build `?next=`) and are not rerendered when the user moves between pages that share them. The decision keeps its intent (the server's session table is the authority, checked on the server) but moves the call into each `(app)` page through a request cached `requireSession(path, searchParams)`, with the AC-10 browser 401 handler as the backstop between already loaded pages. A `proxy.ts` that copies the URL into a header was the alternative fix; it was rejected because it brings back the middleware layer the engineer declined and adds a second reader of the request. Pros: the server is the only authority; no duplicated session logic. Cons: one backend call per server rendered protected page (an indexed lookup, acceptable at household scale per ADR-007), and every new page must call the helper.

**Middleware (`proxy.ts` in Next.js 16) cookie presence check plus the layout check.** Pros: bounces a visitor with no cookie at all slightly earlier. Cons: a second place to keep correct, and it cannot judge a cookie that is present but revoked.

**Middleware only.** Cons: a revoked session still renders the shell; rejected.

### Client address behind the proxy

**Trust `X-Forwarded-For` only from configured proxy addresses (chosen).** The app reads the forwarded address only when the direct peer is a listed proxy, taking the rightmost address that is not a trusted proxy. Pros: per user rate limits survive the proxy; a direct caller cannot spoof an address. Cons: a backend change and a new setting in a frontend ticket; production must list the real proxy address or limits fall back to one bucket.

**How the address leaves Next.js (added 2026-11-05 after the AC-14 live check failed).** The check showed the rewrite never sets `X-Forwarded-For` and keeps a browser supplied one, on both `next dev` and `next build` plus `next start` (Next.js 16.4.5). Next.js also cannot recover the real socket address once a browser has sent the header, and a Route Handler or `proxy.ts` has no API to read the socket directly. Options weighed:

**A `proxy.ts` with an `ENERGYIQ_EDGE_PROXY` flag (chosen).** `false` deletes the header (no spoofing, one shared bucket); `true` passes it through for a trusted edge proxy that appends the real peer. Pros: safe by default, one build serves both topologies, small (one file, one setting), and P8 only flips a value. Cons: a second setting; dev and any direct deployment share one bucket; per address limits depend on an edge proxy that does not exist yet.

**Always pass the header through.** Pros: simplest. Cons: a browser that reaches Next.js directly can send any address and dodge the per client caps (20 logins per 15 minutes, 5 registrations per hour); only safe if an edge is always present, which nothing enforces.

**Always delete the header.** Pros: nothing to configure. Cons: permanent shared bucket, so one client can lock everyone out of login, the exact regression AC-14 exists to prevent; adding an edge later would need this work anyway.

**Replace the rewrite with a Route Handler proxy.** Rejected: it gains nothing (same missing socket access) and means hand writing streaming, `Set-Cookie`, and error forwarding that the rewrite already does.

**A custom Node server that sets the header from the socket.** Rejected for now: it would give true per address limits without an edge, but it replaces the standard Next.js server, breaks the usual deploy targets, and is far more than P3-01 needs. Revisit only if P8 chooses to run Next.js with no edge in front.

**Accept one shared bucket until P8.** Pros: no backend change now. Cons: a single client can lock all users out of login; the regression is invisible in single user development.

**Key proxied requests by email only.** Cons: drops the defense against one client spraying many emails.

### Smaller choices (engineer picked)

| Choice | Picked | Main runner up and why not |
|---|---|---|
| Package manager | pnpm | npm: looser dependency hoisting hides undeclared imports |
| Runtime response checks | Types only; parse only problem bodies | Zod for every response: bundle cost and duplication while FastAPI already validates its output |
| Styling | Tailwind CSS v4 plus shadcn/ui | Tailwind alone: every accessible primitive hand built |
| Forms | react-hook-form plus Zod through the shadcn Form | Server Actions: login's `Set-Cookie` would bypass the ADR-007 rewrite |
| Tests | Vitest, Testing Library, MSW; Playwright in P3-04 | Playwright now: browser install pulled forward |
| Lint and format | ESLint (Next config, jsx-a11y) plus Prettier, `tsc --noEmit` | Biome: fewer Next.js and accessibility rules |
| Backend address | One server only `ENERGYIQ_API_ORIGIN` | Two variables: only useful once hosts split (P8) |
| Language | English, strings in one messages module | Spanish now with `next-intl`: routing and catalogs before any real screen exists |
| Codegen | Committed output plus a drift test | Generated at build: API changes invisible in review |
| 401 mid session | Clear cache, redirect to `/login?next=` | In place re-login dialog: request queue and retry complexity |
| `next` parameter | Same origin relative paths only | Always `/`: loses deep link return |
| Security headers | Baseline now, nonce CSP in P8 | Nonce CSP now: forces dynamic rendering and test complexity |
| API down | Shared error page with retry; inline alert for writes | Redirect to login: misleading |
| Accessibility | jsx-a11y plus axe on the auth forms | Lint only: P3-02 would copy an unchecked pattern |
| Local run | `pnpm dev` on the host | Compose web service: slow, flaky file watching on Windows |

## Rationale

The design is built around one rule: every cross cutting concern lives in exactly one place. ADR-007 already moved credential handling out of page scripts; this spec moves the rest out of individual screens. The mutator is the only code that knows the CSRF header, the base URL, the problem details shape, and which failures mean "the server is unavailable". The server request helper is the only code that touches the incoming cookie. The protected layout is the only session gate. That is what keeps P3-02 to P3-04 small and keeps the trust rules from Context enforceable by a handful of tests rather than by review of every screen.

Server prefetch with hydration was chosen over browser only fetching because the session guard has to run on the server anyway (only the server can see the HttpOnly cookie), so the server is already in the read path, and paying for a client waterfall on top adds latency for nothing. The price is the per request QueryClient and `cache: 'no-store'` discipline. The spec makes both invariants with tests, because a shared cache across requests in a multi user server is exactly the kind of leak the owner isolation work in Phase 2 exists to prevent.

The forwarded address fix belongs in this ticket, not P8, because P3-01 is the change that introduces the proxy. Shipping the proxy without it would silently downgrade a Phase 2 security control the gate already verified. Doing it in the app (Uvicorn's `ProxyHeadersMiddleware` configured from an `ENERGYIQ_` setting) rather than through Uvicorn command flags makes it testable with the existing test client and keeps one documented source of truth. The documented run command turns Uvicorn's own proxy header handling off, so the two cannot disagree.

The Next.js half (AC-18) was added after the live check the spec itself demanded came back negative; the spec said to stop and return to `/architect`, and this is that return. The engineer picked the flag over the two simpler options because it stays safe today and needs only a value change when an edge proxy arrives. The email lockout is keyed on the email, not the address, so a spoofed address could never bypass it; what a spoof defeats is only the per client caps, which is why failing closed (drop the header) is the default.

Readable operation ids are a backend change too (FastAPI defaults to ids like `login_api_v1_auth_login_post`). Deriving ids from route function names is cheap, keeps the generated client readable for every later ticket, and the existing snapshot test turns any accidental rename into a reviewed diff. The runner up, renaming inside Orval's config, would hide the mapping in frontend config and break whenever a route moves.

Settled during writing (my calls, with runner up):

- **Operation ids**: route function name through FastAPI `generate_unique_id_function`, with a test that ids are unique. Runner up: Orval `override.operationName`.
- **Orval layout**: `tags-split` mode (one file per OpenAPI tag: `auth`, `properties`, `meters`, `consumption`, `health`), schemas in a `model` folder. Runner up: a single file, which grows past easy review.
- **Calling the same function on the server**: generated functions accept per call request options; server code passes `serverRequestInit()` from a `server-only` module. Runner up: a dynamic import of `next/headers` inside the mutator, which risks pulling server code into the client bundle.
- **QueryClient defaults**: `staleTime` 60 seconds (hydrated data is not refetched immediately), queries retry once only on `ApiUnavailableError`, never on 4xx, mutations never retry. Runner up: library defaults (three retries on everything, including 401 and 422).
- **Cookie forwarding**: forward only `energyiq_session` and `__Host-energyiq_session`. Runner up: forward the whole cookie header, which leaks unrelated cookies to the API.
- **Idempotency key**: use the typed `Idempotency-Key` header parameter Orval generates for the 7 idempotent POSTs; one key per form submission, reused if that submission is retried. Runner up: a mutator option, which would duplicate the generated parameter.
- **Server Component testing**: keep layouts and pages thin and move logic into plain functions (`requireSession`, `safeNextPath`, `toApiError`) unit tested with MSW; full rendered flows are proven live by `/check verify` and by Playwright in P3-04. Runner up: experimental async Server Component rendering in Vitest, which is unstable.
- **ADR**: record ADR-008 for the frontend data access pattern, because it binds every later screen.

## Cross check (2026-11-04)

An independent read by a different model raised 25 findings. The engineer chose to apply all the recommended fixes. The load bearing ones changed the design: the guard moved from the layout into each page (above); the unavailable state is rendered by the server rather than `error.tsx`, because production Next.js hides the error class and `reset()` does not rerun a server render; the rewrite is documented as bound at build time; the Orval response envelope is turned off; the 401 handler keys on `not_authenticated` with a once only latch; logout's real responses (204, 403, 503, never 401) are used; auth responses and protected pages get `Cache-Control: no-store`; and `prod` must set `ENERGYIQ_FORWARDED_ALLOW_IPS` explicitly. The finding that hydration could be skipped in P3-01 (pass `UserOut` as props) was recorded and not taken: P3-02 needs the pattern, and the request scoped QueryClient makes it safe.

## Version note

No web check was run (References level: none). Versions named in the index (Next.js 16, React 19, Tailwind CSS v4, TanStack Query v5, MSW 2, Zod 4) reflect my knowledge as of this writing. This space moves fast. `/develop` must check each package's current stable release and compatibility before adding it, then pin the exact tested versions in `pnpm-lock.yaml` and in `docs/03-TECH-STACK.md`, as the version policy requires. One behavior in particular must be confirmed live, not assumed: that the Next.js rewrite proxy forwards `X-Forwarded-For` (AC-14). If it does not, stop and return to `/architect` before adding a custom proxy route.
