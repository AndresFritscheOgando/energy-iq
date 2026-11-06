# 0011. Product UI for properties, readings, and consumption

**Date**: 2026-11-05
**Status**: Accepted

## Summary

This umbrella spec covers the rest of Phase 3 (P3-02 to P3-04). A resident can create a property and a meter, enter and void readings, and see measured usage on a chart that marks gaps plainly and never shows missing data as zero. A browser test suite and a one command synthetic demo then prove the whole flow. The screens are built once, against a visual design you produce with Claude Design from the prompt in this folder, and the only backend change is a sort order option on the readings list.

## Structure

| Child | Ticket | What it decides |
|---|---|---|
| [0001 Properties, meters, readings](0001-properties-meters-readings.md) | P3-02 | Nested routes, list and create forms, the reading form with its lower value warning, voiding, and the `order` option on the readings API |
| [0002 Consumption chart](0002-consumption-chart.md) | P3-03 | Stepped kWh per day chart on Recharts, range presets, stat tiles, the intervals and gaps table, and every empty, partial, and error state |
| [0003 Accessibility, end to end, demo](0003-accessibility-e2e-demo.md) | P3-04 | Playwright with axe, a separate `energyiq_e2e` database, and the demo seed script |

Also in this folder: [design-prompt.md](design-prompt.md), the prompt used for the Claude Design handoff. The output is in [docs/screen-references](../../screen-references/README.md), as you directed during the build. Child files are numbered inside this directory only. The next top level spec number is 0012.

## Requirements

**User stories**:
- As a resident, I want to set up a property and meter and log readings, so my usage history builds up in one place (US-003).
- As a resident, I want a graph of usage with gap indicators, so missing data is not mistaken for zero (US-004).
- As an evaluator, I want a repeatable synthetic demo and browser tests, so I can see the product work without real data.

**Acceptance criteria** (umbrella level; each child holds its detailed criteria):
- **AC-1**: Every child's acceptance criteria pass, built in order 0001 → 0002 → 0003.
- **AC-2**: The Phase 3 exit gate holds: a real browser creates a property, a meter, and readings end to end through the same origin proxy and sees the resulting chart (child 0003 journey J1).
- **AC-3**: Acceptance prerequisites are met: spec 0010 is Accepted (`/check verify` for AC-14 and AC-18 and a fresh review), and the Claude Design output is saved in `docs/screen-references/` (see Design handoff). The build began before spec 0010 closed; this timing is recorded in `docs/PROGRESS.md`.
- **AC-4**: Screens follow the handoff: `globals.css` carries its tokens for light and dark, the theme follows `prefers-color-scheme` with no toggle, and any deviation from the prototype is recorded in `docs/PROGRESS.md` with its reason.
- **AC-5**: Docs are current: README (running the demo and the end to end suite), `docs/03-TECH-STACK.md` (new pins), `docs/04-DATA-MODEL-API.md` (the `order` option), the roadmap, and `docs/PROGRESS.md` with the checks actually run. The spec 0005 follow up on calendar day presentation and the spec 0010 follow up on charting and decimals are marked resolved by this spec.

## Decision

**Chosen option**: Nested routes over the ADR-008 data access pattern, a stepped rate chart drawn only from what the API measured, and a real browser suite against its own database.

No estimate, derived daily value, or client computed total ever appears. Every number shown is an API value, exactly rounded for display.

**Implementation skills**: `orval` (`orval-labs/orval`, `.claude/skills/orval/`) · `tanstack-query` (`tanstack-skills/tanstack-skills`, `.claude/skills/tanstack-query/`) · `next-dev-loop` (`vercel/next.js`, `.claude/skills/next-dev-loop/`) · `tailwind-4-docs` (`lombiq/tailwind-agent-skills`, `.claude/skills/tailwind-4-docs/`) · `shadcn` (installed globally) · `vitest` (`antfu/skills`, `.claude/skills/vitest/`) · `msw` (`pproenca/dot-skills`, `.claude/skills/msw/`) · `vercel-react-best-practices` (installed globally) · `fastapi` (`.claude/skills/fastapi/`, for the `order` option) · `playwright-best-practices` (`currents-dev/playwright-best-practices-skill`, `.claude/skills/playwright-best-practices/`) · `accessibility` (`addyosmani/web-quality-skills`, `.claude/skills/accessibility/`)

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

**Data model sketch**: No database change and no migration. The frontend stores nothing beyond the React Query cache. All entities are the Phase 2 tables (spec 0009).

**Routes**:
| Path | Shows | Guard path |
|---|---|---|
| `/` | Property list, create property, "Member since" | `/` |
| `/properties/[propertyId]` | Property details, meters (active and inactive), create meter | `/properties/<id>` |
| `/meters/[meterId]?range=` | Chart, stats, table, reading form, readings list | `/meters/<id>` |

The property list is the roadmap's "property selector": selecting means following a link. There are no automatic redirects. Creating a property opens its page, and creating a meter opens its page.

**Cross child contract** (shared modules, built in child 0001 unless noted):
- `src/components/app/AppPage.tsx`: server component that renders a breadcrumb and page title inside `HydrationBoundary`, plus the account controls (email and sign out, using hydrated `useMe`). `(app)/layout.tsx` stays chrome only and is never the guard.
- `src/lib/api/server.ts` gains `loadOrNotFound(queryOptions, path, searchParams)`, which runs `fetchQuery` and returns `{status: "ok", data}` or `{status: "unavailable", requestId}`, like `SessionState`. A 404 or a 422 on a path id calls `notFound()`. `not_authenticated` redirects through `loginRedirectTarget(path, searchParams)`. Anything else is thrown to `error.tsx`. `redirect()` and `notFound()` are never caught.
- `src/app/(app)/not-found.tsx`: one message with a link to `/`. A foreign, archived, unknown, or malformed id all show it, so existence never leaks.
- `src/lib/api/form-errors.ts`: the field mapping and `genericErrorMessage` move here from `components/auth/auth-errors.ts`, so nothing outside auth imports from auth. `problemToForm(error, fieldMap)` strips `body` from `loc`, uses `en.ts` copy by `code`, and sends unmapped errors to the form alert. `auth-errors.ts` calls it and its tests keep passing.
- `src/lib/decimal.ts`, with no `Number` anywhere:
  - `parseDecimal(text)` accepts `^[0-9]+(\.[0-9]+)?$` of any length (API output varies: `measured_kwh` can be `"0"`, ratios have 4 places, and rates can exceed 12 integer digits) into a scaled `BigInt`. It returns `null` otherwise and never throws, so a render can't crash. A caller shows "Not available" for `null`.
  - `compareDecimal(a, b)` compares exactly.
  - `formatDecimal(value, places)` rounds half even and groups thousands. `formatExact(value)` trims trailing zeros, groups thousands, and never rounds.
  - `formatPercent(ratio, {hasGaps, hasMeasured})` gives a whole percent, half even, except that it says "over 99%" when it would round to 100 with gaps present, and "under 1%" when it would round to 0 with something measured.
- `src/lib/zoned-time.ts`: `zonedInstant(date, time, zone)` returns a UTC instant through a two pass `Intl` offset lookup. A nonexistent local time moves forward to the first valid instant, and an ambiguous one takes the earlier instant. `localToday(zone)` and `windowFor(range, zone, now)` live here too.
- `formatDateTime(value, style, zone)` gains an optional zone, defaulting to `DISPLAY_TIME_ZONE`. Screens pass `PropertyOut.timezone`. `formatLocalDate("YYYY-MM-DD")` formats a plain date with no zone conversion, since `formatDateTime` rejects a value with no offset.
- `src/lib/api/use-idempotency-key.ts`: one `crypto.randomUUID()` per submission. The same key is reused when that submission is retried, and a new one is made after success or after any value changes. The generated client has no idempotency parameter, despite spec 0010's value sourcing table, and generated hooks fix `request` when created. So each form uses `useMutation` around the generated function and passes `{headers: {"Idempotency-Key": key}}` per call. A test proves the header arrives.
- `invalidateMeterData(queryClient, meterId)`: invalidates every readings and consumption query for that meter by key prefix (the generated key functions called with no params). A test proves it matches all ranges and all pages.
- Copy lives in `src/messages/en.ts`. English only, as in spec 0010.

**Page read plan**. Failed prefetches stay out of the hydrated cache, so the browser fetches instead.
| Page | Must load (`loadOrNotFound`) | Prefetch, may fail | Query keys |
|---|---|---|---|
| `/` | `me` through the guard | Properties, first page, `prefetchInfiniteQuery` | Generated key plus `"infinite"` |
| `/properties/[id]` | `me`, property | Meters with `include_inactive=true`, first page | Generated key plus `"infinite"` |
| `/meters/[id]` | `me`, meter, then its property | Readings with `order=desc&limit=50`, first page; consumption with a 2 second timeout, `prefetchQuery` | Readings: generated key plus `"infinite"`. Consumption: generated key with the window |

- **Infinite keys** are `[...generatedKey(id, paramsWithoutCursor), "infinite"]`, so they never collide with a plain query and still match by prefix. `initialPageParam` is `undefined`, and the page param is the cursor.
- **Meter and property** read through hydrated `useGetMeter` and `useGetProperty`, so a client refetch works.
- **List section states**: loading is a skeleton with reserved height. A failed first page shows the section's own message with Retry. A failed "Load more" keeps the rows and shows an inline message with Retry. Copy follows `genericErrorMessage`, and other sections keep working.
- **Prefetch timeout**: `ServerInit` gains an optional `timeoutMs`, defaulting to `SERVER_TIMEOUT_MS`. Only consumption sets it to 2,000, so a slow chart can't hold up the page by more than that.

**Design handoff**: The Claude Design output is in [docs/screen-references](../../screen-references/README.md): the clickable prototype link, `tokens.css`, and the state boards for each screen. The implementation read this handoff before building the screens. Design owns appearance and layout; this spec owns behavior, states, and copy meaning. If they conflict, the spec wins and the deviation is recorded. System fonts stay (ADR-008, no font host).

**Theme**: `globals.css` changes `@custom-variant dark` to `@media (prefers-color-scheme: dark)`, moves the `.dark` block into that media query on `:root`, and sets `color-scheme: light dark`. No dependency, no toggle, no flash on load.

**API surface**: One backend change, `order` on the readings list (child 0001). Everything else is an existing Phase 2 route, listed in each child.

**Value sourcing**: Each child has its own table.

**Key invariants**:
- No authenticated value is computed for authorization in the browser. Ownership stays in the backend.
- kWh, rates, and ratios stay strings. `Number` is allowed in exactly one place: pixel positions inside `toChartModel` (child 0002). No shown value passes through it.
- Every `(app)` page calls `requireSession` first. A test enumerates the `(app)` page files and fails if one does not (the check spec 0010 asked P3-02 to add).
- A gap is never drawn, listed, or summed as zero, and a measured zero is never drawn as a gap.
- Every consequential write is confirmed by the user's explicit action. Void always has a confirm step.
- Only synthetic data appears in tests, the seed, and design artifacts.

**Security model**: Every page needs a session, checked on the server. All data access goes through owner scoped backend routes; a foreign id answers 404 exactly like an unknown one. CSRF, cookies, and error mapping stay in the existing mutator. The demo password is known and public, so the seed script refuses anything except a local dev or test setup (child 0003). No compliance scope beyond the project's existing privacy rules: no real bill or account data.

**Configuration required**: No new runtime setting for the app. `ENERGYIQ_DEMO_PASSWORD` is optional and only read by the seed script. The end to end suite sets its own values (child 0003).

**Critical test scenarios**: See each child. Umbrella level: the full journey J1 in a real browser verifies **AC-2**. The `(app)` page enumeration test verifies the guard invariant. Axe in light and dark verifies **AC-4**.

## Build plan

Ordered as thin end to end slices (no build approach recorded; Tracer Bullet assumed), behind the design handoff you chose to do first.

1. Acceptance prerequisites: confirm spec 0010 is Accepted and `docs/screen-references/` holds the handoff. The implementation started before spec 0010 closed, and that timing is recorded in `docs/PROGRESS.md`. Force stage the handoff with this spec when committing, because `/docs` is ignored and a clean checkout would otherwise miss it, satisfies **AC-3**.
2. Apply tokens and the theme change to `globals.css`, confirm existing screens and the contrast test still pass, satisfies **AC-4**.
3. Build child 0001 (the tracer: create a property, meter, and reading through real servers first, then thicken), satisfies **AC-1**.
4. Build child 0002, satisfies **AC-1**.
5. Build child 0003, including the Phase 3 gate journey, satisfies **AC-1**, **AC-2**.
6. Update docs and run every backend and frontend check, recording actual results, satisfies **AC-5**.

## Consequences

**Positive**:
- The Phase 3 gate is proven in a real browser, and the demo can be rerun at any time.
- Gaps, invalid intervals, and zero usage are visibly different, which is the product's main promise.
- Screens are built once against a real design.

**Negative / tradeoffs**:
- The build waits on a design step only you can run, and on P3-01 closing.
- A long stretch between two valid readings appears as one wide measured step, because the API counts it as measured. It shows an average, not what happened on each day.
- A meter with a real reset keeps its gap until the deferred event screen exists. Only the API can record events for now.
- Names can't be edited, and properties and meters can't be archived or deactivated, in the UI.
- Recharts adds to the meter page's client bundle, and it adds one more dependency to keep current.
- Playwright adds a browser download and a second test run that needs Docker. It stays local until P8 CI.
- The end to end suite owns a production build pointed at its own API port, because the rewrite target is fixed at build time.

**Neutral**:
- `/docs` is ignored by git, so this folder and `docs/screen-references/` need force staging.
- `origin/main` has 9 commits that `features` lacks, including one removing the documentation tree. That needs resolving at merge, separately from this work.

## Follow-up

- [x] Spec 0010's value sourcing table now says forms pass `Idempotency-Key` through `RequestOptions.headers`; the generated client has no typed idempotency parameter.
- [ ] Ticket: meter event screen (record, approve, reject).
- [ ] Ticket: edit names, archive properties, deactivate meters (the first step of a meter replacement, ADR-006).
- [ ] Ticket: register digits on the meter form, when rollover support is designed.
- [ ] Ticket: custom date ranges, likely with Phase 4 bill reconciliation.
- [ ] P8: run `pnpm test:e2e` in CI, and consider Firefox and WebKit.
- [ ] Spanish localization remains its own ticket.
- [ ] Skills: `playwright-best-practices` and `accessibility` were installed for this spec on 2026-11-05 but are not listed in `AGENTS.md`. They belong in the planned nested `frontend/AGENTS.md`, along with the spec 0010 frontend conventions.
- [ ] Skills: no Recharts skill is installed. `recharts/recharts@guide` was installed, found to cover only writing pages for Recharts' own docs site, and removed. `andy-spike/skills@recharts` is an unvetted alternative if you want one.
- [ ] MCP declined on 2026-11-05: Playwright MCP and the community axe server. Record under `Declined:` in `AGENTS.md`.
