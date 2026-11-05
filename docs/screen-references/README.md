# EnergyIQ design: product UI for readings and consumption

Design reference for spec 0011. Everything here is a visual reference; the
prototype is not production code.

- **Canvas (prototype and state boards):** https://claude.ai/artifact/HbgFB2EB4LEkHu3VpFU7H9
- **Tokens:** [`tokens.css`](./tokens.css)

## What's on the canvas

| Artboard | What it shows |
| --- | --- |
| Prototype (click through) | Home, Property, Meter, Not found and Server unreachable in one interactive artboard. A dark strip on top (labelled as prototype-only) switches scenarios: lists loading or failing, usage loading, failing or out of date, save can't reach the server, meter deactivated before saving, void fails once, Load more fails once, inactive meter, new account, server unreachable. The theme follows the device. |
| Meter, 1280 | Full meter screen in light and dark, plus the inactive meter. |
| Meter, 390 and 320 | One-column layout (form first) in light and dark at 390, and light at 320. Only the intervals table scrolls sideways, inside its own region. |
| Meter, usage states | Loading, needs readings, partial (normal), partial at 30 days, nothing measured at 30 and 365 days, section error, couldn't refresh, coverage extremes. Light and dark. |
| Meter, reading form states | Idle, saving, saved, field error, same date conflict, lower value warning, server unreachable, meter no longer active. Light and dark. |
| Meter, readings and void | Filled, voided row, empty, loading, failed, Load more, Load more failed, void dialog idle, working and failed. Light and dark. |
| Chart spec | The four marks side by side, hatch geometry at 4x, spike and measured-zero edge cases, focus and selection, 365 days at 390, interaction rules. |
| Home, Property, Not found and server unreachable | Every state from the brief. |
| Tokens | Every token in both themes, the contrast table, type scale and shape rules. |

## Decisions

**Accent: teal.** Teal reads calm and precise, and it leaves amber free to mean
"check this": the lower-value warning, the dropped-reading band and the
out-of-date banner all use the amber family. If the accent were amber, warnings
would need a second warm hue and brand color would collide with meaning.

**Neutrals:** warm stone at very low chroma (hue 65 to 80, chroma under 0.012),
so the UI feels warm without turning beige.

**Chart.** Measured usage, measured zero and gaps differ by shape and texture,
not only color:

| Mark | Shape | Never confused with |
| --- | --- | --- |
| Measured use | Filled step (`--chart-measured` at 20%) with a 2 px top line at its average rate, as wide as its real duration. | |
| Measured, no use | A 3 px bar lying on the baseline with 8 px end ticks. No fill, no hatching. | The 1 px axis (thinner, no ticks) and a gap (hatched). |
| No measured usage (gap) | 45 degree hatching across the full plot height. No top line. | Zero use: a gap has hatching and no bar. |
| Reading dropped (invalid gap) | Cross-hatching in `--chart-invalid` plus a small downward marker above the band. | A plain gap: different texture, plus the marker survives at 3 px wide. |

Other chart rules:

- x is real time across the range, y is kWh per day from 0.
- Drawn items keep a 3 px minimum width; click and tap hit areas are at least 12 px wide.
- **Spikes:** if the tallest step is more than 3 times the next tallest, the axis follows the next one, the tall step is cut with a break mark, its true value is written above it, and the caption says so.
- **Selection:** a 2 px `--foreground` outline on the selected step or band, and its table row is highlighted. The newest measured step is selected by default.
- **Keyboard:** the plot is one tab stop. Left and Right move through items in time order, Home and End jump to the ends. Focus shows a 2 px `--ring` outline with 4 px offset around the plot.
- **Readout:** under the plot at every width, never over the data. It reserves 52 px (72 px narrow), uses `aria-live="polite"`, and reads like "Nov 1 to Nov 8: 4.00 kWh per day, 28.00 kWh, average over 7 days". A band reads like "Oct 25 to Nov 1, 7 days: No measured usage. The reading dropped with no recorded reset or replacement, so no usage is counted."
- **Out of date:** amber "Out of date" banner with reference and Retry, an "As of 9:41 AM" badge on the chart, and measured marks turn grey. Three cues, none of them color alone.
- **Partial note:** quiet muted text with an info icon, never an alert box. Coverage reads "over 99%" or "under 1%" at the extremes and is never rounded to 0% or 100%.
- The intervals table is the accessible equivalent of the chart.

## Hatch patterns (rebuild as SVG `<pattern>`)

```svg
<!-- Gap: 45 degree lines, 6 px apart, 1.25 px stroke -->
<pattern id="hatch-gap" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
  <rect width="6" height="6" style="fill: color-mix(in oklch, var(--chart-gap) 7%, transparent)" />
  <line x1="0" y1="0" x2="0" y2="6" style="stroke: var(--chart-gap); stroke-width: 1.25" />
</pattern>

<!-- Reading dropped: cross-hatch at +45 and -45 degrees, 8 px apart, 1.25 px stroke -->
<pattern id="hatch-invalid" patternUnits="userSpaceOnUse" width="8" height="8" patternTransform="rotate(45)">
  <rect width="8" height="8" style="fill: color-mix(in oklch, var(--chart-invalid) 8%, transparent)" />
  <line x1="0" y1="0" x2="0" y2="8" style="stroke: var(--chart-invalid); stroke-width: 1.25" />
  <line x1="0" y1="0" x2="8" y2="0" style="stroke: var(--chart-invalid); stroke-width: 1.25" />
</pattern>
```

Dropped-reading marker: a 10 x 7 px downward triangle filled with
`--chart-invalid`, centred on the band, its tip 2 px above the plot top.
Give pattern ids a per-chart suffix (for example with React `useId`), because
`url(#id)` resolves document-wide.

## Tokens

All values are `oklch` and use the shadcn names. Additions beyond shadcn:
`--chart-measured`, `--chart-gap`, `--chart-invalid` (from the brief) and
`--warning`, `--warning-foreground` (needed by the lower-value warning and the
out-of-date banner; the brief's list has no warning color). `--chart-1` to
`--chart-3` mirror measured, gap and invalid; `--chart-4` and `--chart-5` are
spare.

Destructive buttons follow base-nova's subtle style: `--destructive` text on
`--destructive` at 10% over the card, so no `--destructive-foreground` is needed.

### Contrast (computed from the oklch values)

Text needs 4.5:1; graphics, input borders and focus rings need 3:1.

| Pairing | Tokens | Light | Dark | Needs |
| --- | --- | --- | --- | --- |
| Body text on page | `--foreground` on `--background` | 16.98:1 | 16.16:1 | 4.5:1 |
| Body text on card | `--card-foreground` on `--card` | 17.58:1 | 15.19:1 | 4.5:1 |
| Popover text | `--popover-foreground` on `--popover` | 17.58:1 | 14.53:1 | 4.5:1 |
| Secondary text on page | `--muted-foreground` on `--background` | 6.28:1 | 7.48:1 | 4.5:1 |
| Secondary text on card | `--muted-foreground` on `--card` | 6.50:1 | 7.03:1 | 4.5:1 |
| Secondary text on muted | `--muted-foreground` on `--muted` | 5.75:1 | 6.22:1 | 4.5:1 |
| Primary button label | `--primary-foreground` on `--primary` | 6.22:1 | 8.33:1 | 4.5:1 |
| Link text on card | `--primary` on `--card` | 6.44:1 | 8.20:1 | 4.5:1 |
| Secondary button label | `--secondary-foreground` on `--secondary` | 14.05:1 | 12.27:1 | 4.5:1 |
| Hover/selected item label | `--accent-foreground` on `--accent` | 10.29:1 | 10.25:1 | 4.5:1 |
| Error text on card | `--destructive` on `--card` | 5.99:1 | 6.32:1 | 4.5:1 |
| Void button label (destructive/10 on card) | `--destructive` on `--destructive 10% over --card` | 5.18:1 | 5.62:1 | 4.5:1 |
| Warning title (warning-foreground on warning/10) | `--warning-foreground` on `--warning 10% over --card` | 8.29:1 | 10.17:1 | 4.5:1 |
| Warning body (foreground on warning/10) | `--foreground` on `--warning 10% over --card` | 15.64:1 | 13.13:1 | 4.5:1 |
| Chart axis labels on card | `--muted-foreground` on `--card` | 6.50:1 | 7.03:1 | 4.5:1 |
| Input border on card | `--input` on `--card` | 3.62:1 | 3.43:1 | 3:1 |
| Focus ring on page | `--ring` on `--background` | 4.45:1 | 8.12:1 | 3:1 |
| Focus ring on card | `--ring` on `--card` | 4.60:1 | 7.63:1 | 3:1 |
| Measured step line on card | `--chart-measured` on `--card` | 5.21:1 | 8.20:1 | 3:1 |
| Gap hatch on card | `--chart-gap` on `--card` | 3.92:1 | 3.89:1 | 3:1 |
| Dropped-reading hatch on card | `--chart-invalid` on `--card` | 4.38:1 | 7.94:1 | 3:1 |
| Selected outline (foreground) on card | `--foreground` on `--card` | 17.58:1 | 15.19:1 | 3:1 |
| Warning icon and border on card | `--warning` on `--card` | 4.01:1 | 8.89:1 | 3:1 |

`--border` is decorative only (dividers next to text that already identifies
the region), so it is not held to 3:1. Inputs use `--input`, which passes.

### Type scale (system stack, tabular numerals everywhere)

| Role | Size / line height, weight |
| --- | --- |
| Page title | 24 / 32, 600 |
| Stat value | 30 / 36, 500 (22 / 28 under 640 px) |
| Section title | 16 / 24, 600 |
| Body | 14 / 20, 400 |
| Secondary | 13 / 18 to 20, 400, `--muted-foreground` |
| Small | 12 / 16, 400 to 600 |
| Chart axis | 11, `--muted-foreground` |

Font stack: `ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto,
"Helvetica Neue", Arial, "Noto Sans", sans-serif`. Set
`font-variant-numeric: tabular-nums` once on the app root.

### Shape and layout

- `--radius: 0.5rem`. Cards, alerts, tables and lists 8 px; buttons, inputs and selects 6 px; dialogs 12 px; badges are pills.
- Controls are 36 px tall on desktop and 44 px under 640 px wide.
- Content max width 1200 px. Meter: main column plus a 320 px side column with a 24 px gutter; one column under 900 px with the form first (it is also first in the DOM, so tab order matches).
- Focus: 2 px `--ring` outline, 2 px offset, on every control. Inputs swap to a `--ring` border plus a 3 px halo at 35%.

## Sample data

The brief's six readings are used exactly. Its quoted stats (589.50 kWh,
13.71 kWh per day, 84%) can't come from those readings, so every number on the
canvas is computed from them instead. The prototype's clock is fixed at
**November 14, 2026** so the November 8 reading is in the past.

| Range | Measured | Average per day | Coverage | Measured days |
| --- | --- | --- | --- | --- |
| 30 days | 28.00 kWh | 4.00 kWh | 23% | 7 days of 30 |
| 90 days | 28.00 kWh | 4.00 kWh | 8% | 7 days of 90 |
| 365 days | 113.00 kWh | 0.47 kWh | 67% | 243 days of 365 |

365-day intervals, newest first:

| From | To | Length | kWh | kWh per day | Note |
| --- | --- | --- | --- | --- | --- |
| Nov 8, 2026 | Nov 14, 2026 | 6 days | No measured usage | | No reading yet after this date. |
| Nov 1, 2026 | Nov 8, 2026 | 7 days | 28.00 | 4.00 | |
| Oct 25, 2026 | Nov 1, 2026 | 7 days | No measured usage | | The reading dropped with no recorded reset or replacement, so no usage is counted. |
| Mar 18, 2026 | Oct 25, 2026 | 221 days | 42.00 | 0.19 | |
| Mar 10, 2026 | Mar 18, 2026 | 8 days | 28.00 | 3.50 | |
| Mar 3, 2026 | Mar 10, 2026 | 7 days | 15.00 | 2.14 | |
| Nov 14, 2025 | Mar 3, 2026 | 109 days | No measured usage | | Before your first reading. |

A few extra invented rows appear only where a state needs them: two more
property nicknames ("Beach apartment", "Workshop") for Load more, an "Old meter"
for the inactive marker, and a separate illustrative dataset on the chart spec
board for the spike and measured-zero cases. Reference codes such as
`EIQ-4F2A-91C7` are placeholders.

## Notes for the build

- The prototype draws the intervals table with ARIA table roles only because of
  a canvas limitation; the app should use a real `<table>` like the state boards.
- Hand-drawn icons on the canvas follow lucide shapes (info, circle-alert,
  triangle-alert, circle-check, clock, chevron-right, rotate-cw, cloud-off),
  which shadcn/ui already ships through lucide-react.
- No toggle, settings, bills, forecasts, assistant, name editing or daily
  estimates were added.
