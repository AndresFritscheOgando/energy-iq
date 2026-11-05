# Verify: P3-01 Next.js foundation · spec 0010 · updated 2026-11-05
_Steps derived from spec 0010 acceptance criteria and its Value sourcing table. `/check verify` runs these; `/test` locks the durable ones._

Setup: PostgreSQL up and migrated; `$env:ENERGYIQ_ENV = "dev"`; Uvicorn with `--no-access-log --no-proxy-headers`; `cd frontend; pnpm dev` (or `pnpm build` then `pnpm start` with `ENERGYIQ_API_ORIGIN=http://127.0.0.1:8000`). Open exactly `http://localhost:3000`. If port 3000 is busy, use `-p 3100` and start the API with `ENERGYIQ_TRUSTED_ORIGINS='["http://localhost:3100"]'`.

## UI / manual (real browser, DevTools Network tab open)
- [x] Signed out, open `/` → redirected to `/login?next=%2F` → AC-6
- [x] Signed out, open `/?tab=week` → redirected to `/login?next=%2F%3Ftab%3Dweek` (path plus query from `searchParams`) → AC-6, Value sourcing "Session guard redirect"
- [x] `/register` with a new synthetic email and a 5 character password → hint shows "You have 5 characters", submit is not blocked, the password field shows the `en.ts` length copy (not the server message), and focus lands on it → AC-8, AC-15, Value sourcing "Field error copy"
- [x] Type `ﬁ` in the register password → the hint counts 2 characters (NFKC) → AC-8
- [x] Register with a 12+ character password → lands on `/` showing "Signed in as <email>" and "Member since <today in Santo Domingo>" → AC-5, AC-8, AC-16, Value sourcing "Home page"
- [x] On that first load the Network tab shows no browser request to `/api/v1/auth/me` (hydrated from the server) → AC-5
- [x] DevTools Application tab: `energyiq_session` is HttpOnly; no token in localStorage, sessionStorage, or any URL → Key invariants
- [x] Register the same email again → "An account with this email already exists." on the email field with a "Sign in instead" link to `/login` → AC-8
- [x] While signed in, open `/login` and `/register` → both redirect to `/` → AC-6
- [x] Click Sign out → full page load of `/login` (Network shows a document request), then press Back → no signed in content is shown (`no-store`) → AC-9, AC-13
- [x] Login with a wrong password → one form alert "Email or password is incorrect.", on neither field, focus on the alert → AC-7, AC-15
- [x] Six wrong passwords for one email → "Too many attempts. Try again in N minutes." with N = `Retry-After` rounded up → AC-7, Value sourcing "429 message"
- [x] Open `/login?next=%2F%2Fevil.example`, sign in → lands on `/`, never another site; `/login?next=%2Fproperties%3Fx%3D1` → lands on `/properties?x=1` → AC-11, Value sourcing "Post login target"
- [x] Submit an empty login form → focus moves to Email with "Enter your email."; no request is sent → AC-15
- [x] Double click Sign in quickly → one `/api/v1/auth/login` request; the button shows "Signing in…" and is disabled → AC-15
- [x] Open the app at `http://127.0.0.1:3000/login` and sign in → the dev CSRF message naming `http://localhost:3000` → AC-12, Value sourcing "Backend Origin check" and "CSRF failure copy"
- [x] Signed in on `/`, revoke the session (sign out in a second tab), then trigger a client query or mutation in the first tab → one navigation to `/login?next=...`, cache cleared → AC-10
- [x] Stop Uvicorn, reload `/` → "EnergyIQ can't reach its server right now." with Retry, not a login redirect → AC-6, AC-12
- [x] With Uvicorn stopped, click Sign out → inline unavailable alert; restart Uvicorn, click Retry → home renders with the same session → AC-9, AC-12, Value sourcing "Unavailable and fallback reference"
- [x] axe DevTools (or Lighthouse) on `/login` and `/register` in idle, field error, and form error states → zero violations, including color contrast → AC-15

## Commands
- [x] `cd frontend; pnpm lint; pnpm typecheck; pnpm test; pnpm format:check` → all pass, lint with 0 warnings → AC-1, AC-15
- [x] `pnpm build` without `ENERGYIQ_API_ORIGIN` → fails naming the variable; with it → passes, `/`, `/login`, `/register` are dynamic → AC-1, AC-2, Value sourcing "Rewrite and server fetch"
- [x] After a build, `pnpm test` → the bundle test runs (not skipped) and `.next/static` holds no `127.0.0.1:8000` → AC-2
- [x] Hand edit a file in `src/lib/api/generated/`, run `pnpm test` → the drift test fails; `pnpm gen:api` restores it → AC-3, Value sourcing "Generated types"
- [x] `curl -sI http://localhost:3000/login` → the five security headers, `no-store`, no `X-Powered-By` → AC-13
- [x] `curl -s -X POST -H "X-EnergyIQ-CSRF: 1" -D - http://localhost:3000/api/v1/auth/logout` → 204 with `cache-control: no-store` → AC-13
- [x] With `ENERGYIQ_EDGE_PROXY=true`, a wrong password login through `http://localhost:3000/api/v1/auth/login` with `X-Forwarded-For: 198.51.100.77` → the new `auth_attempts.client_key` equals `HMAC(secret, "198.51.100.77")`; the same call straight to `:8000` from a non loopback peer ignores the header → AC-14, AC-18, Value sourcing "Rate limit key"
- [x] With `ENERGYIQ_EDGE_PROXY=false` (and unset in dev), the same call → the stored `client_key` equals `HMAC(secret, "127.0.0.1")`, never the sent address → AC-18
- [x] Echo server in place of FastAPI, `next start` run once per value without a rebuild: `false` → plain and spoofed requests both arrive with no `X-Forwarded-For`; `true` → `6.6.6.6` arrives as sent and a plain request arrives with the socket address → AC-18, Value sourcing "Whether Next.js forwards the client address"
- [x] `next build` and `next start` with `ENERGYIQ_EDGE_PROXY` unset (and a `NODE_ENV=production` start) → fails naming `ENERGYIQ_EDGE_PROXY`; the value `yes` fails the same way → AC-18
- [x] `ENERGYIQ_ENV=prod` with every other secret set but no `ENERGYIQ_FORWARDED_ALLOW_IPS` → startup fails naming `forwarded_allow_ips` → AC-14
- [x] `ENERGYIQ_REQUIRE_DB=1 uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` → all pass → AC-3, AC-13, AC-14, AC-17
- [x] Count `"route":"/api/v1/auth/me"` lines in the API log while loading `/` once → exactly 1 → AC-5

## Acceptance-criteria coverage
- AC-1: commands 1, 2 · AC-2: commands 2, 3 · AC-3: command 4, backend suite (`test_operation_ids_are_route_names_and_unique`), `tests/api/generated-types.test.ts` · AC-4: `tests/api/fetcher.*.test.ts`, UI unavailable steps · AC-5: UI hydration step, command 13 · AC-6: UI redirect and unavailable steps · AC-7: UI wrong password, 429, next steps · AC-8: UI register steps · AC-9: UI sign out steps · AC-10: UI revoke step · AC-11: UI next step, `tests/lib/safe-next.test.ts` · AC-12: UI CSRF and outage steps · AC-13: UI back button, commands 5, 6 · AC-14: commands 7, 11 · AC-18: commands 7, 8, 9, 10 and the `proxy.ts` unit tests · AC-15: UI focus, pending, axe steps, command 1 · AC-16: UI home step, `tests/lib/format.test.ts` · AC-17: README, `03-TECH-STACK`, ADR-008, PROGRESS (reviewed by hand)
