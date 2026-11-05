# Accessibility, end to end tests, and demo seed (P3-04)

## Summary

This child proves Phase 3 in a real browser. Playwright runs the whole flow against real servers and its own throwaway database, and axe checks every screen in light and dark. A small script fills a local account with synthetic readings, so anyone can sign in and see steps, gaps, and an unexplained decrease within a minute.

## Requirements

**Acceptance criteria**:
- **AC-1**: Suite. `pnpm test:e2e` runs three steps in this order: the database reset, a production build, then Playwright from `frontend/e2e/` on Chromium with `retries: 0` and `workers: 1`. Playwright has a desktop project at 1280 wide and a narrow project at 390 wide. Vitest does not pick these files up. It needs only Docker's database running and installed browsers, and prints a clear message when the database is unreachable.
- **AC-2**: Isolated database. `backend/scripts/reset_e2e_db.py --database energyiq_e2e` refuses any other name. It connects as the migrator (the host, role, and password from `local_database_url("test", migrator=True)`, or `ENERGYIQ_MIGRATION_DATABASE_URL` when set) to the `postgres` database, drops and recreates the target with the grants of the `scratch` fixture in `backend/tests/db/conftest.py`, then runs Alembic upgrade head with `ENERGYIQ_ENV=test` and both database URLs set for `energyiq_e2e`. The servers aren't running at that point, so it uses a plain `DROP DATABASE IF EXISTS`. If another process holds a connection, it prints "stop the process using energyiq_e2e" and exits nonzero. The dev and test databases are never touched. A new database also clears the rate limit rows.
- **AC-3**: Servers. The build sets `ENERGYIQ_API_ORIGIN=http://127.0.0.1:8100`, `ENERGYIQ_EDGE_PROXY=false`, and `ENERGYIQ_NEXT_DIST_DIR=.next-e2e`, which `next.config.ts` uses as `distDir`, so your normal `.next` keeps its own rewrite target. `.next-e2e` is added to the Git, ESLint, and Prettier ignore lists. Playwright then starts Uvicorn on port 8100 (with `--no-proxy-headers`, `ENERGYIQ_ENV=test`, explicit database URLs for `energyiq_e2e`, and `ENERGYIQ_TRUSTED_ORIGINS=["http://localhost:3100"]`) and `next start -p 3100` with the same variables. It never reuses a running server, so results can't depend on your dev servers.
- **AC-4**: Rate limits respected. With `ENERGYIQ_EDGE_PROXY=false`, all browsers share one bucket of 5 registers per hour and 20 logins per 15 minutes, of any outcome. The suite registers exactly 4 accounts and reuses signed in state through `storageState`:
  | Account | Registered by | Used by |
  |---|---|---|
  | `shared` | setup project | J2 to J7, J9, narrow smoke, axe for filled states |
  | `pristine` | setup project, never writes | axe for empty home, J8 as the second user |
  | `gate` | J1 itself | J1 |
  | `demo@example.test` | the seed, in J10 | J10 |

  Journeys run in the desktop project only. The narrow project runs one smoke test (open the meter page, save a reading) and the axe and reflow checks. A fixture fails any test that receives a 429. Logins total under 10 per run.
- **AC-5**: Journeys, each a test:
  - **J1 gate**: register → empty home → create property → create meter → first reading → "needs readings" state → second reading → a step on the chart with matching stat and table values, all through the same origin proxy.
  - **J2 decrease**: a lower value warns, "Save anyway" saves, and a hatched band and the unexplained decrease note appear. Voiding that reading removes the gap.
  - **J3 zero versus gap**: equal readings draw a step on the baseline with no hatching, and a value of 0 in the table, while the time after the last reading stays hatched with no number.
  - **J4 range**: switching ranges updates the URL and content; back returns; a bad `range` shows 90 days.
  - **J5 refresh**: saving a reading updates the chart with no reload.
  - **J6 failed refresh**: hydrated data makes no browser consumption call on load, so the test first adds a `page.route` that fulfills consumption with a 500 `application/problem+json` body carrying `code` and `request_id`, then saves a reading. "Reading saved" appears, the old chart is marked out of date with the reference, and the form still works. After the route is removed, Retry shows the new data.
  - **J7 prefetch fallback**: covered by child 0002 AC-10's Vitest tests, since a browser can't intercept a server call and no fault route is added to the app. It has no Playwright test.
  - **J8 cross user**: the `pristine` account opening `shared`'s meter and property URLs gets the not found page, the same as an unknown id.
  - **J9 session lost**: clearing the cookie mid use sends the next browser call to `/login?next=...` once, and signing in returns to the page.
  - **J10 demo**: the seed script runs twice against this stack, then its login shows exactly one demo property with steps, hatching, and the decrease note in the 365 day range.
- **AC-6**: Axe. `@axe-core/playwright` with WCAG 2.1 A and AA tags reports zero violations on exactly these screens and states: login, register, home (empty, filled), property (empty, filled), meter (needs readings, nothing measured, partial, couldn't refresh, form error, warning open, void dialog open, inactive), and not found, in light and dark through `colorScheme` emulation, at both widths. Inactive is reached by deactivating a meter through the API in the test. Loading states and the first page failure are checked with `vitest-axe`. Any exclusion needs a written reason in the test.
- **AC-7**: Keyboard and reflow. A keyboard only test creates a reading, handles the warning, opens and cancels a void with focus returning, and moves through chart segments with the readout announcing each. Focus is always visible. At 320 wide, the page has no horizontal scroll (the table scrolls in its own region). Status changes are announced through live regions.
- **AC-8**: Seed safety. `backend/scripts/seed_demo.py` lives outside the shipped package and uses only the public API (with `httpx2`, cookie session, CSRF header). It exits nonzero with a clear message, before any request, unless `ENERGYIQ_ENV` is `dev` or `test` and the API URL host is exactly `127.0.0.1`, `localhost`, or `::1`. It never prints the cookie.
- **AC-9**: Seed account. `demo@example.test`, with the password from `ENERGYIQ_DEMO_PASSWORD` or the documented dev only default `energyiq-demo-local-only`. It logs in, and registers only on `invalid_credentials`. Each failure exits nonzero with a clear message and no retry: a 429 prints the wait; a 409 `email_taken` after a failed login says the password differs from the one that made the account and how to recreate the database; a 422 says the password must be 12 to 128 characters.
- **AC-10**: Seed content. Each run archives the account's existing properties, then creates "Demo home" with one EDESUR meter "Main meter", so a rerun always ends with one fresh property. Readings are `local_date` values relative to today in `America/Santo_Domingo`, from a fixed list with no randomness and no real data:
  - about weekly readings starting about 300 days ago, so the 365 day range shows time before the first reading;
  - one stretch of about 6 weeks with no readings, which appears as one wide step labelled as an average;
  - one reading about 10 weeks ago lower than the one before it, which appears as an invalid interval with its note, with later readings rising from the lower value;
  - a last reading about 3 days ago, which leaves a short stretch after the last reading.
  It prints the app URL, email, and password at the end.
- **AC-11**: Docs. README gets "Run the demo" (database, migrate, API, web, seed, sign in) and "Run the end to end suite", including `pnpm exec playwright install chromium`. `pyrightconfig.json` includes `backend/scripts`, and Ruff covers it.

## Decision

Playwright with `@axe-core/playwright` on Chromium, a dedicated database rebuilt per run, and a seed script that goes through the real API.

- **Test accounts**: the AC-4 table. Runner up: a test only bypass of rate limits, which would add a security sensitive switch to the app.
- **Build before Playwright**: a chained step, not a `webServer` command, so build time can't hit Playwright's startup timeout. Runner up: a long `webServer` timeout, which hides build failures inside server startup.
- **Own `distDir`**: the e2e build would otherwise leave a `.next` pointing at port 8100, and a later `next start` would silently hit a dead port. This is the one setting added for tests. It changes only where build output goes.
- **Ports**: fixed 3100 and 8100, because the rewrite target is fixed at build time and the CSRF origin must match. Runner up: random ports, which would need a rebuild each time anyway and make failures harder to reproduce.
- **`ENERGYIQ_ENV=test` for the API**: gives test defaults while the database URLs are set explicitly.
- **Seed reruns archive**: the API has no delete, and archived names are free for reuse, so reruns stay clean with dates near today.
- **Default demo password**: a known value, because the API has no password reset and a rerun must be able to sign in. The loopback and env refusal is what makes this acceptable.
- **Not run in this ticket**: CI (P8), Firefox and WebKit, visual snapshots.

**Inline rationale**: Vitest with jsdom can't check contrast, real focus, or Recharts drawing, and those are the risks left in this phase. Going through the API means the demo can only contain data the product itself can produce. Each browser test shares its database with the others in the run, so tests create their own properties rather than relying on shared rows.

## Feature design

**API surface**: No new route. The seed uses `/auth/login`, `/auth/register`, `GET`, `POST`, and `DELETE /properties`, `POST /properties/{id}/meters`, and `POST /meters/{id}/readings`.

**Value sourcing**:
| Action | Value | Source |
|---|---|---|
| Seed target | API URL | `--api-url`, default `http://127.0.0.1:8000`, loopback only |
| Seed gate | Environment | `ENERGYIQ_ENV`, required, `dev` or `test` |
| Seed credentials | Email, password | Constant `demo@example.test`; `ENERGYIQ_DEMO_PASSWORD` or the default `energyiq-demo-local-only` |
| Build output folder | `distDir` | `ENERGYIQ_NEXT_DIST_DIR`, default `.next` |
| Seed dates | `local_date` | Today in `America/Santo_Domingo` via `zoneinfo`, minus the fixed offsets |
| Seed values | `cumulative_kwh` | Fixed list in the script, as decimal strings |
| Seed idempotency | `Idempotency-Key` | A new `uuid4` per request |
| Reset script | Migrator connection | `ENERGYIQ_MIGRATION_DATABASE_URL` when set, else `local_database_url("test", migrator=True)`; host and role only, with the database replaced by `postgres` |
| Reset script | Target name | `--database`, refused unless exactly `energyiq_e2e` |
| Suite | App and migrator URLs | The same local defaults with the database replaced by `energyiq_e2e`, passed to Uvicorn and Alembic |
| Suite | Ports, origins, flags | Constants in `playwright.config.ts` |
| Test accounts | Email, password | Generated per run under `@example.test` |

**Key invariants**:
- The reset script can only ever drop `energyiq_e2e`.
- The seed never runs against a non loopback API or a `prod` environment.
- Tests use synthetic data only, and do not depend on run order except through the shared signed in state.

**Security model**: The known demo password is safe only under the seed's refusals, and those are tested. The suite's secrets are local test values, not real credentials. No production code path or bypass is added for tests. The only added setting, `ENERGYIQ_NEXT_DIST_DIR`, affects build output location alone.

**Critical test scenarios**:
- The journeys in AC-5 verify **AC-5**, and through them the Phase 3 gate.
- Axe matrix, verifies **AC-6**.
- Keyboard journey and 320 wide reflow, verifies **AC-7**.
- Seed refusal: `prod`, unset env, and a non loopback URL each exit nonzero with no request sent (pytest with a mock transport that fails if called), verifies **AC-8**.
- Reset refusal: another database name exits nonzero and drops nothing; a held connection prints the stop message, verifies **AC-2**.
- Seed run twice leaves one active property and the listed stories, verifies **AC-9**, **AC-10**.
- Seed failures: `email_taken` after a failed login, a short password 422, and a 429 each exit nonzero with their message (pytest with a mock transport), verifies **AC-9**.
- A 429 anywhere fails the test through the fixture, verifies **AC-4**.

## Build plan

1. Add Playwright and `@axe-core/playwright` at verified current pins, `reset_e2e_db.py`, `ENERGYIQ_NEXT_DIST_DIR`, config, server startup, and the setup project that registers `shared` and `pristine`. Confirm the reset works against the real roles early, because its privileges were reasoned about rather than tested, satisfies **AC-1**, **AC-2**, **AC-3**, **AC-4**.
2. Journey J1, the Phase 3 gate, satisfies **AC-5**.
3. `seed_demo.py` with refusal tests, content, and journey J10, satisfies **AC-8**, **AC-9**, **AC-10**, **AC-5**.
4. Journeys J2 to J9, satisfies **AC-5**.
5. Axe matrix, keyboard journey, reflow; fix what they find, satisfies **AC-6**, **AC-7**.
6. README and tooling config, satisfies **AC-11**.
