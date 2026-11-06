# 0011 Rationale

## Context

P3-01 gave the app sign in and a typed API layer but no product screens. The Phase 3 gate needs a real browser to create a property, a meter, and readings. US-004 needs a chart where missing data can't be mistaken for zero.

Forces that shaped the choices:
- The consumption API returns uneven intervals and typed gaps for a window of up to 366 days. It has no daily series.
- Reading values can't be edited, so a typo stays until voided. A decrease is preserved, not rejected.
- The readings list was ascending only, with a forward only cursor.
- kWh values are exact decimal strings, and project rules forbid binary floats for totals.
- With `ENERGYIQ_EDGE_PROXY=false`, every browser shares one rate limit bucket, which limits how a test suite can register accounts.
- The rewrite target is fixed at build time.
- Solo developer, no CI until P8, and a portfolio goal of a reproducible demo.

## Options considered

**Routes.** Nested routes (chosen) give each page its own guard and prefetch, a working back button, and shareable links, at the cost of more page files. One dashboard with query params has fewer pages, but one page holds every state. A dashboard plus a manage page separates reading from setup, but adds trips for new users.

**Correcting readings.** List and void (chosen) is the smallest set that makes a typo fixable. Adding flag exposes a state most users won't need. List only requires an API call to fix a typo.

**Meter events.** Explain and defer (chosen) keeps to the roadmap, and the gap stays accurate. A full event screen is complete but is a whole extra workflow. A read only list can't show anything the UI could create.

**Chart library.** Recharts through shadcn (chosen) matches the owned component kit and draws axes, steps, and bands, with a moderate bundle. Hand written SVG adds no dependency, renders on the server, and gives each step and band its own focusable element, but you then own axes and resizing. A same model cross check recommended it, because this chart is only rectangles and its band tooltips need custom code on Recharts anyway. You reviewed that and kept Recharts, so the spec settles the drawing and adds an app owned readout. visx is precise but more code, and outside the shadcn pattern. ECharts is capable but large, with its own styling path.

**Chart loading.** Server prefetch with a 2 second limit (chosen) keeps instant data under ADR-008 and stops a slow chart from holding up the form. Browser only is simplest, but shows a skeleton on every load. The normal 10 second limit could delay the whole page, against the rule that sections fail on their own.

**Chart shape.** Stepped rate (chosen) stays comparable across uneven widths and invents nothing, but shows an average rather than daily detail. Bars of total kWh are easy to read, but longer spans look like higher use. Estimated daily bars look familiar, but add derived numbers.

**Long stretches.** A wide step labelled as an average (chosen) agrees with the API's coverage figure. Fading past a threshold adds a number no domain rule defines. Hatching contradicts coverage and stats.

**Lower value check.** Nearest earlier reading (chosen) keeps backfills quiet, at the cost of one lookup on submit. The newest reading needs no request, but warns on every backfill. Checking both neighbors catches more, with more requests and copy.

**Readings order.** An `order=desc` option (chosen) solves both the list and the lookup with a small change, but touches the shared pagination helper. A dedicated route is narrow, and leaves the list oldest first. A frontend only window can't page through older data and misses backfills outside the window.

**Decimals.** A small BigInt helper (chosen) has no dependency and fits the fixed API format, but is code to own. big.js is less code, but a dependency for two operations. decimal.js is larger than needed.

**End to end tool.** Playwright plus axe on Chromium (chosen) gives real contrast and focus checks, at the cost of a browser download. All three engines cost run time and flakiness for now. Cypress has no advantage here. Vitest plus a manual pass can't be rerun.

**End to end data.** A fresh `energyiq_e2e` (chosen) is isolated and clears rate limit rows, but needs a setup script. Sharing `energyiq_test` conflicts with pytest. The dev database pollutes your data.

**Seed.** A script through the API (chosen) can only make data the product can make, but needs a running server. Direct inserts skip rules and audit. Static fixtures go stale as dates age out of the window.

**Design timing.** Design first (chosen) builds screens once and lets the design shape the chart, but blocks on a step only you can run. A thin thread first avoids waiting, but styles some screens twice.

**Theme switching.** Following the system setting (chosen) needs no dependency or load flash, but gives users no override. `next-themes` and a cookie toggle both add code for little value now.

## Rationale

The product's promise is that it never invents data, and most decisions follow from that: a chart shape that needs no estimates, drawing only `measured_in_window` intervals so the chart can't disagree with the stats, and exact decimal display. Scope stays near the roadmap because each extra screen (events, editing) would bring its own states into a phase whose gate only needs create and read, and the honest gap remains correct until those arrive.

The one backend change was found during design: the planned warning and newest first list both need a direction the API lacked. Fixing the route is cheaper than working around it in the browser, and the default keeps every existing caller unchanged.

Real browser tests are worth their setup here because the remaining risks (contrast, focus, chart drawing) are the ones jsdom can't see. A dedicated database also works around the shared rate limit bucket without adding a test only bypass to the app.
