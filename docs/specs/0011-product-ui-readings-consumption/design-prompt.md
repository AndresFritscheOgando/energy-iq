# Claude Design prompt for EnergyIQ Phase 3

The output from this prompt is saved in `docs/screen-references/`: `tokens.css`, the state boards, and the prototype link in `README.md`. You directed this location during the build.

---

Design the core product screens for **EnergyIQ**, a self hosted web app where residents in the Dominican Republic log their electricity meter readings and see how much power they use. It is not a utility portal, and it must not look like one. All text is in English for now. Use only the invented sample data below.

## Personality

A **calm instrument**: quiet, precise, trustworthy, like a well made measuring tool. Numbers lead. Missing data is stated plainly, without alarm. No gradients for decoration, no stock illustrations, no marketing tone, no gamification.

## Visual direction

- **Color**: warm neutrals plus one energy accent (propose amber or teal, and say which you chose and why). Keep color free to carry meaning.
- **Theme**: specify light and dark equally. The app follows the device setting, so do not design a toggle.
- **Layout**: desktop first at 1280 wide, with a working narrow layout at 390 wide. Nothing may scroll sideways at 320 wide, except a table inside its own region.
- **Type**: system font stack only, no hosted fonts. Use tabular numerals for all figures. Define a type scale.
- **Components**: the app uses shadcn/ui (Base UI, base-nova style) with Tailwind CSS 4. Stay close to those component shapes so the design can be built directly.
- **Accessibility**: WCAG 2.1 AA contrast in both themes, visible focus on every control, and no meaning carried by color alone.

## Screens

**App frame on every signed in page**: product name, breadcrumb, the user's email, and a sign out control.

**1. Home (`/`)**: the user's properties, each a link showing its nickname and optional region. A form to create a property: nickname (required), region (optional). "Member since November 4, 2026" appears quietly on this page.

**2. Property (`/properties/[id]`)**: property name and region, its meters (label, distributor, an "Inactive" marker when inactive), and a form to create a meter: label (required) and distributor (a native select: EDESUR, EDEESTE, EDENORTE, Other).

**3. Meter (`/meters/[id]`)**: the main screen. At desktop width:
- The **main column** holds a range control (30 days, 90 days, 365 days), three stat tiles (measured kWh, average kWh per day, coverage percent), then the usage chart.
- A **side column** holds the reading form, always visible without a click: value in kWh, date (defaults to today), optional time, and a save button.
- **Below**, full width: the intervals and gaps table, then the readings list.
- At narrow width, the form moves to the top.

**The reading list** shows date, value, and status text, with a Void action on each row. Voided rows are struck through and still say "Voided" in text.

**Void dialog**: a confirm step that names the value and date. Voiding can't be undone.

## The chart (the most important design decision)

Readings arrive at uneven gaps, so the chart is **not** daily bars.

- The x axis is real time across the selected range. The y axis is kWh per day, starting at 0.
- **Measured usage** is a flat **step** at its average rate, as wide as its real duration. Steps can be 3 days or 43 days wide.
- **Gaps** are **hatched bands** across their span, where no usage is known. These are the moments before the first reading, after the last reading, at the edges of the range, and where a reading dropped without explanation.
- Three things must never be confused, in either theme and without relying on color: **measured use**, **measured zero use** (a step lying on the baseline with no hatching), and **a gap** (hatching with no step).
- Consider whether an invalid gap (the reading dropped) deserves a slightly different treatment from a plain gap, while staying calm. Propose tokens for it.
- Show a legend, a text summary caption under the chart, and a details readout for the selected step or band. Users select by pointer or with the arrow keys, and the selected item is visibly marked. Design where the readout sits so it works at both widths, and show the chart's focus state. A step's readout reads, for example, "Oct 2 to Nov 14: 13.71 kWh per day, 589.50 kWh, average over 43 days". A band's readout gives its plain reason.
- The chart area also has to read well when a step or band is very thin in the 365 day view, and when one huge spike flattens every other step.

## The table

Merges measured stretches and gaps, newest first: from, to, length, kWh, kWh per day, note. Gap rows say "No measured usage" rather than a zero. Sample notes:
- "Before your first reading."
- "No reading yet after this date."
- "The reading dropped with no recorded reset or replacement, so no usage is counted."
- "A span between two readings crosses the edge of this range, so it isn't counted here. Try a longer range."

## States to draw (a board per screen, side by side)

- **Home**: empty (no properties), filled, list loading, list failed with Retry, "Load more" and its inline failure, form field error ("This name is already in use").
- **Property**: no meters, filled with one inactive meter, list loading, list failed with Retry, form error.
- **Meter, usage section**:
  - Loading (skeleton with reserved height).
  - Needs readings: "Add at least two readings to see usage", pointing to the form, with no empty axes.
  - Nothing measured in this range: bands and table show, with a notice linking to a longer range. At 365 days there is no link.
  - **Partial, the normal state** that nearly every user sees all the time: chart plus a calm note such as "84% of this range is measured. Gaps are marked, never counted as zero." It must not feel like a warning. Coverage can read "over 99%" or "under 1%" at the extremes.
  - Section error with nothing to show: its own message, a reference code and a Retry control, while the reading form beside it still works.
  - Couldn't refresh: the earlier chart stays, clearly marked as out of date, with a reference and Retry. It must never look current.
- **Meter, reading form**:
  - Idle, saving, and saved ("Reading saved").
  - Field error ("Use digits and up to 6 decimals, like 13049.5").
  - Same date conflict ("A reading already exists for this date. Add a different time, or void the existing one.").
  - **Lower value warning**: "This is lower than your earlier reading of 13,049 kWh on October 25, 2026. If the earlier reading is wrong, void it." with a link to that reading, and "Save anyway" and "Change value". This asks for confirmation; it is not an error.
  - Form alerts: server unreachable with the typed values kept, and "This meter is no longer active".
- **Meter, readings list**: empty, loading, failed with Retry, "Load more" and its inline failure.
- **Void dialog**: idle, working, and failed with the dialog still open.
- **Meter, inactive**: a note replaces the form, and everything else stays.
- **Not found**: one sentence and a link home.
- **Server unreachable**: "EnergyIQ can't reach its server right now.", a reference, and Retry.

## Sample data (invented)

Property "Demo home", region "Santo Domingo". Meter "Main meter", EDESUR.
Readings in kWh: 12,964 (Mar 3) · 12,979 (Mar 10) · 13,007 (Mar 18) · 13,049 (Oct 25) · 13,012 (Nov 1, a drop) · 13,040 (Nov 8).
Stats: 589.50 kWh measured, 13.71 kWh per day, 84% coverage. Use your own consistent numbers for the chart. Never use real names, addresses, or account numbers.

## What to hand back

1. **A clickable prototype** linking all screens and the key states above, as a visual reference. It won't be used as production code.
2. **Design tokens** as a `tokens.css` file with `:root` values and a `@media (prefers-color-scheme: dark)` override, in `oklch`, using exactly these shadcn variable names: `--background`, `--foreground`, `--card`, `--card-foreground`, `--popover`, `--popover-foreground`, `--primary`, `--primary-foreground`, `--secondary`, `--secondary-foreground`, `--muted`, `--muted-foreground`, `--accent`, `--accent-foreground`, `--destructive`, `--border`, `--input`, `--ring`, `--chart-1` to `--chart-5`, `--radius`, plus new ones: `--chart-measured`, `--chart-gap`, `--chart-invalid`. Describe the hatch pattern (angle, spacing, stroke) so it can be rebuilt as an SVG pattern. Give the contrast ratio of each text and chart pairing in each theme.
3. **A state board per screen** showing every state above side by side, in both themes for the meter screen.

Don't add features beyond this brief: no settings page, no theme toggle, no bills, no forecasts, no AI assistant, no editing of names, no daily estimates.
