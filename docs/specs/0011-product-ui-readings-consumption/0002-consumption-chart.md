# Consumption chart and summary (P3-03)

## Summary

This child adds the meter page's usage view: a stepped chart of kWh per day, three summary numbers, and a table listing every measured stretch and gap with a plain reason. Everything comes straight from the consumption API, with no daily estimates. A gap has its own visual treatment, so nobody can mistake missing data for zero use. The chart can fail by itself while entering readings keeps working.

## Requirements

**Acceptance criteria**:
- **AC-1**: Window. `?range=` accepts `30d`, `90d`, `365d`; anything else, or nothing, means `90d`, with no error. The server computes it once: `to` is the start of tomorrow in the property's zone, and `from` is local midnight N calendar days before `to`. The window passes to the client as a prop, so server and browser share one query key. Range controls are links with `aria-current` on the active one, so back and shared links work. A test proves `365d` never exceeds the API's 366 day limit, including in a DST zone.
- **AC-2**: Stats. Three tiles: measured kWh (`measured_kwh`), average kWh per day (`average_kwh_per_day`, or "Not available" when null), and coverage (`coverage_ratio` through `formatPercent`). Displayed values use `formatDecimal` at 2 places and `formatPercent`, both exact and half even. Coverage never says 100% when gaps exist or 0% when something is measured.
- **AC-3**: Chart. A real time axis spans exactly the window. Each interval with `measured_in_window: true` is one flat step at its `kwh_per_day`, from `start` to `end`. Each entry in `gaps` is a hatched band across its span. Nothing else is drawn: invalid and partial intervals appear only through their gap. The y axis starts at 0 and is labelled kWh per day. Animation is off. Drawing is settled as follows:
  - **Series**: `ComposedChart` with a numeric time `XAxis` whose domain is the window, and one `Line` with `type="linear"`, `dot={false}`, and `connectNulls={false}`. Each step adds the points `(start, rate)`, `(end, rate)`, then `(end, null)`, so adjacent steps have no vertical connector.
  - **Bands**: one `ReferenceArea` per gap, filled with an SVG hatch pattern defined in the chart.
  - **Y domain**: `[0, top]`, where `top` is the next nice number above the largest measured rate. All zero or nothing measured uses `[0, 1]`. No clipping: a huge spike flattens the other steps, and the table still shows their exact values.
  - **Narrow spans**: a band narrower than 2 pixels is drawn 2 pixels wide, as a render step only, so the model's exact spans and the tiling test are unaffected. Steps have a stroke wide enough to stay visible.
  - **Server rendering**: the chart is loaded with `dynamic(..., {ssr: false})` behind a reserved height skeleton. Tiles, caption, and table still render on the server when the prefetch succeeded.
  - **Test hooks**: `Line` and each `ReferenceArea` carry class names `chart-step`, `chart-band`, and `chart-band--invalid`.
- **AC-4**: Gap versus zero. A measured rate of `0.000000` draws a step on the baseline with no hatching; a gap draws hatching with no step. The difference holds without color (hatch pattern and legend) and in both themes. Steps and bands tile the window exactly, with no hole and no overlap.
- **AC-5**: Details on hover and focus. Recharts' tooltip and keyboard layer are off, since they follow data points and can't be expected to reach bands. A small `ChartReadout` owned by this app reads `model.segments`, the ordered list of steps and bands that tile the window. The chart wrapper has `tabIndex={0}` and an accessible name: Left and Right move through segments, Home and End jump to the ends. Pointer movement selects the segment under the cursor, by converting x to time from the chart's fixed margins and fixed y axis width. The readout shows the span and the exact strings from the model: the rate, total kWh, and the length note for a step; the plain reason for a band. It sits in a polite live region, and the selected segment is visibly marked.
- **AC-6**: Table. An always visible table lists measured intervals and gaps merged, newest first: from, to, length, kWh, kWh per day, note. kWh and kWh per day use `formatDecimal` at 2 places, the same as the tiles and readout. Gaps show "No measured usage" rather than 0 in the numeric columns. Measured rows show the length note: "Average over N days" using whole days rounded half even when the interval is at least 1 day, otherwise "Average over N hours", with "under 1 hour" below that. The table scrolls in its own region on narrow screens.
- **AC-7**: Plain reasons. Each gap's note comes from `en.ts`, by `reason` and, for invalid intervals, `interval_reason`. All values have copy:
  - `before_first_reading`: Before your first reading.
  - `after_last_reading`: No reading yet after this date.
  - `no_intervals`: Not enough readings to measure usage.
  - `partial_interval`: A span between two readings crosses the edge of this range, so it isn't counted here. Try a longer range.
  - `unexplained_decrease`: The reading dropped with no recorded reset or replacement, so no usage is counted.
  - `flagged_reading`: A reading here is flagged, so no usage is counted.
  - `unapproved_event`: A meter event here isn't approved yet, so no usage is counted.
  - `meter_boundary`: The meter was reset or replaced here, so usage isn't counted across it.
  - `unsupported_event`: A meter event here can't be calculated yet, so no usage is counted.
  - Any unknown value: No measured usage here.
- **AC-8**: Accessible chart. The chart is in a `figure` whose caption states the range, measured kWh, average, coverage, and gap count, and points to the table as the full equivalent. Contrast passes in both themes.
- **AC-9**: States, in this order:
  - Loading: tile and chart skeletons with reserved height, and a polite status message.
  - Error with no data: the section shows its own message with Retry that refetches. `ApiUnavailableError` uses the unavailable copy and `ApiError` the fallback with its request id. The reading form and list keep working.
  - Couldn't refresh: a refetch failed while earlier data exists (query `isError` with `data` present). The old chart, tiles, and table stay, with a notice marking them out of date, the reference when known, and Retry. It never looks current.
  - Needs readings: every gap is `no_intervals` (fewer than two non voided readings): "Add at least two readings to see usage", pointing at the form, with no empty axes.
  - Nothing measured: no measured interval but other gaps exist, so the window is outside the history or wholly invalid. Stats show their real values, bands and table render, and a notice says no usage is measured in this range. If a longer preset exists, it links to the next longer one; at 365 days it suggests nothing.
  - Partial, the normal state: some measured and gaps exist. The chart plus the notice "N of this range is measured. Gaps are marked, never counted as zero.", where N comes from `formatPercent`. Because `to` is the start of tomorrow and `from` is rarely a reading's exact instant, real meters nearly always have gaps.
  - No gaps: `gaps.length === 0`, with no notice. Kept as a defensive branch, tested only with MSW. It is not a state a user should expect.
- **AC-10**: Server prefetch. The page uses `prefetchQuery` with `timeoutMs: 2000`, so a failed or slow consumption call neither fails the page nor delays it by more than 2 seconds. The section renders its loading state on the server without sending an anonymous request, then the browser fetches. A hard failure of the meter or property load still follows the umbrella's `loadOrNotFound`. Vitest proves this: the page renders with a failing consumption fetch, and rendering the section to a string with an empty client never calls `apiFetch`. A `/check verify` step confirms no `ServerFetchWithoutInitError` appears on a live server.
- **AC-11**: Refresh. After a reading is saved or voided, the chart, stats, and table update through `invalidateMeterData` with no page reload, and the previous data stays visible until the new data arrives, or until the failure becomes the "Couldn't refresh" state.

## Decision

Stepped kWh per day on Recharts through the shadcn chart component, drawn from a pure, separately tested model.

- **Model first**: `src/lib/consumption/chart-model.ts`, `toChartModel(response, zone)`, returns chart points, bands, `segments`, and table rows, each holding exact display strings plus numeric positions. Jsdom can't lay out Recharts, so the logic is tested here and the drawing in a real browser (child 0003). Runner up: logic inside the component, which can't be tested without a browser.
- **`Number` use**: `y` and `x` positions only, inside the model. Tooltips and tables read the strings.
- **Length text**: parse the API's ISO 8601 `duration` (including fractional seconds such as `PT1.5S`) into days and hours, rather than subtracting timestamps in the client.
- **Readout over Recharts' tooltip**: you kept Recharts, and bands must have tooltips and keyboard access. An app owned readout covers steps and bands the same way and can be tested in jsdom. Runner up: turning bands into hidden data points, which ties the model to Recharts internals.
- **Trailing window**: `to` is the start of tomorrow instead of now, so the query key is stable through the day and a date only reading (noon) from today is always inside. The cost is that today's future hours count as uncovered, which a 90 day view barely shows.
- **Stale day boundary**: a page left open across midnight keeps its old window until navigation, or until a save past `to` refreshes it (child 0001 AC-8). Accepted, since it is correct for the range it states.
- **Version check and draw check**: pin the current stable Recharts and confirm React 19.3 support at install, then confirm the series, null separators, hatch, and class names draw as specified in a real browser. If they can't, stop and return to `/architect` rather than switching silently.

**Inline rationale**: The API returns uneven intervals, not days, so a stepped rate is the honest shape: uneven widths stay comparable, and nothing needs estimating. Bars of total kWh would make longer spans look like higher use, and estimated daily bars would add numbers the API never stated. A long stretch stays one wide step because the API counts it as measured, and hatching it would contradict the coverage number beside it.

## Feature design

**API surface**:
| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors handled |
|---|---|---|---|---|---|
| `/meters/{id}/consumption` | GET | `from`, `to` (offset timestamps) | `measured_kwh`, `average_kwh_per_day`, `coverage_ratio`, `covered`, `uncovered`, `intervals[]`, `gaps[]`, `window` | session | 404, 422, 503 |

**Value sourcing**:
| Action | Value | Source |
|---|---|---|
| Longer range link | Next preset | The next longer value in the fixed preset list, none at `365d` |
| Readout selection | Segment | `model.segments`, by keyboard index or pointer x converted using the window and fixed chart margins |
| Y axis top | Number | Next nice number above the largest measured rate position, `1` when none or all zero |
| Window `from`, `to` | Instants | `windowFor(range, PropertyOut.timezone, server now)`; range from `searchParams` |
| Server now | Clock | `new Date()` in the Server Component, passed down as the computed window |
| Query key | Window | The prop, never recomputed in the browser |
| Tiles | Numbers | Response fields through `decimal.ts` |
| Steps | Position, rate | `intervals[]` with `measured_in_window`; `start`, `end`, `kwh_per_day` |
| Step total | kWh | `intervals[].consumption_kwh` |
| Bands | Span, reason | `gaps[].start`, `end`, `reason`, `interval_reason` |
| Gap count | Number | `gaps.length` |
| Length | Days and hours | `duration` of the interval or gap |
| Dates | Zone | `PropertyOut.timezone` through `formatDateTime` |
| Notes | Copy | `en.ts` by reason code |
| Colors, hatch | Style | `--chart-measured`, `--chart-gap`, `--chart-invalid` from `docs/screen-references/tokens.css` |

**Key invariants**:
- The client computes no consumption, average, or coverage value.
- Only `measured_in_window: true` intervals draw as steps, so the chart always agrees with the stats.
- Forecasts and estimates do not exist on this surface.

**Security model**: As the umbrella. The route is owner scoped and holds a share lock in the backend. No value is logged in the browser.

**Critical test scenarios**:
- Model: mixed response tiles the window exactly; rate zero becomes a step, not a band; invalid and partial intervals produce no step; unknown reason falls back; `Number` output never reaches a display string, verifies **AC-3**, **AC-4**, **AC-6**, **AC-7**.
- `windowFor`: each preset in Santo Domingo and in New York across DST; invalid range defaults; 365d within the limit, verifies **AC-1**.
- Each state renders with MSW, including zero and null average, verifies **AC-2**, **AC-9**.
- Duration and length note table (`P1DT2H30M`, `PT6H`, `PT1.5S`, half even at 1.5 days), verifies **AC-6**.
- Readout: arrows move through steps and bands in order, Home and End work, pointer x maps to the right segment, verifies **AC-5**.
- Section failure leaves the form working, and Retry recovers; a failed refetch with data shows "Couldn't refresh", verifies **AC-9**, **AC-11**.
- Page renders with a failing consumption prefetch, and section render never calls `apiFetch`, verifies **AC-10**.
- Real browser drawing, keyboard readout, and refresh after save are in child 0003, verifies **AC-3**, **AC-5**, **AC-11**.

## Build plan

1. `windowFor`, `range` handling, prefetch on the meter page, tiles from real data as the tracer, satisfies **AC-1**, **AC-2**, **AC-10**.
2. `toChartModel` and its tests, satisfies **AC-3**, **AC-4**, **AC-6**.
3. Add Recharts through the shadcn chart component after the version and draw checks, then draw steps, bands, hatch, axes, and legend, satisfies **AC-3**, **AC-4**.
4. `ChartReadout`, figure caption, keyboard behavior, satisfies **AC-5**, **AC-8**.
5. Table and all reason copy, satisfies **AC-6**, **AC-7**.
6. Every state and the section error, then refresh behavior with child 0001's mutations, satisfies **AC-9**, **AC-11**.
