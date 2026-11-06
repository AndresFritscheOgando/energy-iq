# Properties, meters, and readings screens (P3-02)

## Summary

This child builds the screens that put data into EnergyIQ: list and create properties, list and create meters, enter readings, and void a mistaken one. Because reading values can't be edited, voiding is the only way to fix a typo. The form warns before saving a value lower than the nearest earlier reading, without blocking it. The readings API gains an `order` option so the app can ask for newest first.

## Requirements

**Acceptance criteria**:
- **AC-1**: Readings order. `GET /api/v1/meters/{id}/readings` accepts `order` of `asc` (default, unchanged behavior) or `desc`, which sorts by `(recorded_at, id)` descending and pages backward with the same cursor format. An unknown value is 422 `invalid_enum`. `keyset_page` gains a direction argument; properties, meters, and events keep ascending order. Backend tests cover `desc` paging across a full set with no row lost or repeated, `desc` with `to`, `status`, and `limit=1`, default order unchanged, and the 404 for a foreign meter. The OpenAPI snapshot and generated client are updated in the same change, and the drift test passes.
- **AC-2**: Home. `/` lists the user's properties (nickname, region when set), each linking to its page, with "Load more" when `next_cursor` exists. With none, it shows an empty state that leads to the create form. The account block shows email and sign out, and "Member since" stays on this page (spec 0010 AC-16).
- **AC-3**: Create property. Fields are nickname (required) and region (optional). No time zone field: the API default applies. Success invalidates the property list (`getListPropertiesQueryKey()` prefix) and opens `/properties/<id>`, so going back shows the new row. A 409 `property_name_taken` shows on the nickname field. 422 errors map to fields through `problemToForm`.
- **AC-4**: Property page. It shows the property's details and all its meters (`include_inactive=true`), with label, distributor, and an "Inactive" marker when inactive. With none, an empty state leads to the create form. An unknown, foreign, or archived id shows the not found page.
- **AC-5**: Create meter. Fields are label (required) and distributor (required, no default, native select with labels EDESUR, EDEESTE, EDENORTE, and Other, sending the `Distributor` values, so Other sends `OTHER`). No register digits field. Success invalidates that property's meter list (`getListMetersQueryKey(propertyId)` prefix) and opens `/meters/<id>`. A 409 `meter_label_taken` shows on the label field. A 404 from an archived property shows the form alert with a link to `/`.
- **AC-6**: Reading form. On an active meter's page: value (text, decimal keyboard), date (defaults to today in the property's zone, future dates not selectable), and optional time. The first `today` comes from the server as a prop, so hydration can't mismatch. The form recomputes `localToday` when the date field gets focus and before submit, so a tab left open past midnight can still pick the new date. Before any request, the value must match `^[0-9]{1,12}(\.[0-9]{1,6})?$`, otherwise a field error shows the expected format. A comma is not converted. Date only sends `{cumulative_kwh, local_date}`. Date and time sends `{cumulative_kwh, recorded_at}` from `zonedInstant` in the property's zone. `source` and `status` are omitted (API defaults).
- **AC-7**: Lower value warning. On a valid submit, the form computes the entered instant (noon local for date only, as the backend does) and asks for `order=desc&to=<instant>&status=valid&limit=1` through `queryClient.fetchQuery` with `staleTime: 0`, so a 401 still reaches the global handler. If an earlier valid reading exists and `compareDecimal` finds the new value lower, nothing is saved. An alert states the earlier value and date, says "If the earlier reading is wrong, void it" with a link that scrolls to and focuses that row when it is loaded (an earlier mistyped high value makes a correct reading look low), and offers "Save anyway" and "Change value". Focus moves to the alert. Editing any field clears the warning. A backfill above its earlier neighbor is not warned, whatever the newest reading is. If the lookup fails for any reason other than 401, the reading is saved with no warning, because the API preserves the value and the chart reports it.
- **AC-8**: Save results. Success clears the value and time, keeps the date, announces "Reading saved" in a polite live region, returns focus to the value field, and calls `invalidateMeterData`. If the saved `recorded_at` is at or past the chart window's `to` (the page was left open across midnight), it also calls `router.refresh()`, so the server computes a new window and the reading appears. The same `Idempotency-Key` is used if that submission is retried (including "Save anyway"). A 409 `reading_exists_at_instant` shows on the date field with copy telling the user to add a different time or void the existing reading. A 422 `reading_in_future` shows on the date or time field by `loc`. `invalid_kwh` shows on the value. A 409 `meter_inactive` shows a form alert and refetches the meter. An `ApiUnavailableError` shows the inline unavailable alert and keeps the typed values.
- **AC-9**: Readings list. Newest first, 50 per page, "Load more". Each row shows `original_local_date` through `formatLocalDate` when set, otherwise `recorded_at` as date and time in the property's zone. It shows the value through `formatExact`, and a text status for flagged or voided. Voided rows are visibly struck through and still say "Voided" in text. With none, it shows an empty state. Loading and failure follow the umbrella's list section states.
- **AC-10**: Void. A non voided row has a Void action that opens a confirm dialog naming the value and date. Confirming sends `PATCH {status: "voided"}`. Success closes the dialog, returns focus sensibly (the next row's action, or the list heading), announces the result, and calls `invalidateMeterData`. Voiding an already voided reading (another tab, for example) answers 200 from the API and behaves as a normal success, so there is no separate branch. Other failures show inside the dialog, which stays open. Cancel changes nothing. Flagging is not offered.
- **AC-11**: Inactive meter. The page says it is inactive and replaces the reading form with that note. The list, chart, and Void stay available, since the status route allows it.
- **AC-12**: Forms and accessibility. Every form uses the `CredentialsForm` conventions: visible labels, `aria-describedby` and `aria-invalid`, `role="alert"` at form level, focus on the first invalid field or the alert, pending state, double submit blocked. `vitest-axe` reports zero violations for each form in idle, field error, and form error states.
- **AC-13**: Guard test. A Vitest test parses every `page.tsx` under `src/app/(app)/` with the TypeScript compiler API and fails unless `requireSession` is the first awaited call in the default export, ignoring awaits of `params` and `searchParams`, and comes before any data call.

## Decision

Nested server rendered pages with client forms, using hand built `useInfiniteQuery` over generated list functions for paging.

- **Paging**: `useInfiniteQuery` calling generated `listReadings` and friends. Runner up: Orval's infinite hooks, which would regenerate every list route and change config for three call sites.
- **Distributor control**: a native `<select>` styled with tokens. Runner up: shadcn's Base UI select, which adds portal and focus work for four fixed values. A handoff that shows another control does not change this unless you ask.
- **Register digits**: left out, since rollover is an unsupported event today and the field would do nothing visible.
- **Lookup timing**: on submit rather than while typing, so no request runs per keystroke.

**Inline rationale**: A wrong reading damages the chart and can't be edited, so voiding and the warning are the two guards that matter. Comparing with the nearest earlier reading, not the newest, keeps backfills quiet. The lookup is fail open because the backend's rule is to preserve decreases, so a missed warning loses nothing.

## Feature design

**State transitions** (reading, as the UI exposes it): `valid` → `voided` by a confirmed user action. `flagged` → `voided` too, for rows flagged through the API. `voided` is terminal.

**API surface**:
| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors handled |
|---|---|---|---|---|---|
| `/properties` | GET | `limit`, `cursor` | `Page[PropertyOut]` | session | 503 |
| `/properties` | POST | `nickname` (req), `region` (opt), `Idempotency-Key` | `PropertyOut` | session, CSRF | 409 `property_name_taken`, 422 |
| `/properties/{id}` | GET | path id | `PropertyOut` | session | 404, 422 |
| `/properties/{id}/meters` | GET | `include_inactive=true`, `limit`, `cursor` | `Page[MeterOut]` | session | 404 |
| `/properties/{id}/meters` | POST | `label` (req), `distributor` (req), `Idempotency-Key` | `MeterOut` | session, CSRF | 404, 409 `meter_label_taken`, 422 |
| `/meters/{id}` | GET | path id | `MeterOut` | session | 404, 422 |
| `/meters/{id}/readings` | GET | `order` (new), `from`, `to`, `status`, `limit`, `cursor` | `Page[ReadingOut]` | session | 404, 422 |
| `/meters/{id}/readings` | POST | `cumulative_kwh` (req), one of `local_date` or `recorded_at`, `Idempotency-Key` | `ReadingOut` | session, CSRF | 409 `reading_exists_at_instant`, 409 `meter_inactive`, 422 |
| `/meters/{id}/readings/{reading_id}` | PATCH | `status: "voided"` | `ReadingOut`, 200 even when already voided | session, CSRF | 404 |

`/meters/{id}` pages fetch the meter, then its property by `MeterOut.property_id`, because the zone lives on the property.

**Value sourcing**:
| Action | Value | Source |
|---|---|---|
| Any date shown or defaulted on a meter page | Time zone | `PropertyOut.timezone`, from `MeterOut.property_id` |
| Reading form default | Today | Server prop from `localToday(PropertyOut.timezone)`, recomputed in the browser on focus and submit |
| Date only request | `local_date` | The date input, unconverted |
| Date and time request | `recorded_at` | `zonedInstant(date, time, zone)` |
| Warning lookup | `to` | `zonedInstant(date, time or 12:00, zone)`; `to` is exclusive in the API |
| Warning copy | Earlier value and date | First item of the lookup response |
| Lower check | Comparison | `compareDecimal(entered, earlier.cumulative_kwh)`, exact |
| Row value | Displayed kWh | `ReadingOut.cumulative_kwh` through `formatExact`, never rounded |
| Row date | Date or date and time | `original_local_date` through `formatLocalDate`, else `recorded_at` through `formatDateTime` in the property's zone |
| Create POSTs | `Idempotency-Key` | `use-idempotency-key`, passed as a per call header |
| Distributor value | Enum sent | `Distributor` from the generated model; the label `Other` maps to `OTHER` |
| Field errors | Copy | `en.ts` by error `code`, new codes: `invalid_kwh`, `reading_in_future`, `invalid_datetime`, `datetime_out_of_range` |
| New name conflict and collision copy | Copy | `en.ts` by problem `code` |

**Key invariants**:
- Client checks exist for fast feedback; the server's 422 and 409 are the authority.
- The form never rounds, trims, or converts the typed value. What is sent is what was typed.
- No save happens between a warning appearing and an explicit "Save anyway".
- Mutations always invalidate both readings and consumption for that meter.

**Security model**: As the umbrella. `reading_exists_at_instant` carries `existing_reading_id`, which is only ever the owner's own reading. No id in a URL is trusted for anything except asking the API.

**Critical test scenarios**:
- Backend: `desc` paging and filters, default order unchanged, cross user 404, verifies **AC-1**.
- MSW and component: each form's field error, form error, and conflict mapping, verifies **AC-3**, **AC-5**, **AC-8**.
- Decimal table: `compareDecimal` on `9.5` vs `10`, `13049.000000` vs `13049`, the maximum `999999999999.999999`, and a rate with more than 12 integer digits; `measured_kwh` of `"0"`; rounding half even at the boundary; `formatExact` never rounds; malformed input returns `null`; `formatPercent` extremes, verifies **AC-7**, **AC-9**.
- Creating a property or meter then going back shows the new row within the 60 second fresh window, verifies **AC-3**, **AC-5**.
- List section states: first page failure with Retry, and "Load more" failure keeping rows, verifies **AC-2**, **AC-4**, **AC-9**.
- Zone table: Santo Domingo; New York across both DST changes (gap moves forward, overlap takes the earlier instant), verifies **AC-6**.
- Warning: lower than earlier warns and saves nothing until confirmed; backfill above its earlier neighbor but below the newest does not warn; equal does not warn; no earlier reading does not warn; lookup 503 saves with no warning; lookup 401 goes to login, verifies **AC-7**.
- Retry with the same submission reuses the key; a changed value makes a new one, verifies **AC-8**.
- Void: confirm, cancel, a repeat void answering 200 as in the real API, failure keeps the dialog open, focus return, verifies **AC-10**.
- Enumerated `(app)` guard check, verified failing against a scratch page without the guard, verifies **AC-13**.
- Axe per form state, verifies **AC-12**.

## Build plan

1. Backend `order` option, `keyset_page` direction, tests, OpenAPI snapshot, `pnpm gen:api`, satisfies **AC-1**.
2. Tracer: `AppPage`, `loadOrNotFound`, `not-found.tsx`, the three pages with minimal create forms and no polish, and one reading saved through real servers, satisfies **AC-2**, **AC-4**, **AC-6**, **AC-13**.
3. `decimal.ts`, `zoned-time.ts`, `formatDateTime` zone argument, with their tables, satisfies **AC-6**, **AC-9**.
4. `form-errors.ts`, `use-idempotency-key.ts`, full property and meter forms, empty states, paging, satisfies **AC-2**, **AC-3**, **AC-4**, **AC-5**.
5. Full reading form, error mapping, save results, satisfies **AC-6**, **AC-8**.
6. Lower value warning, satisfies **AC-7**.
7. Readings list, void dialog (add the shadcn alert dialog), `invalidateMeterData`, inactive meter state, satisfies **AC-9**, **AC-10**, **AC-11**.
8. Accessibility pass and axe tests, satisfies **AC-12**.
