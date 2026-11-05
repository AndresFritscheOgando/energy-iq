/**
 * The consumption response as chart points, bands, segments, and table rows
 * (spec 0011 child 0002). Pure, so the logic is tested without a browser.
 *
 * `Number` appears here and nowhere else in the app's value handling, and only
 * for pixel positions (`x`, `y`, `yTop`, ticks). Every string a person reads
 * comes from the API value through `decimal.ts`.
 */
import { addLocalDays, zonedInstant } from "@/lib/zoned-time";
import { formatDecimal, isZeroDecimal, parseDecimal } from "@/lib/decimal";
import { formatDateTime } from "@/lib/format";
import { formatLength } from "@/lib/consumption/duration";
import type { GapOut, IntervalOut } from "@/lib/api/generated/model";
import { en } from "@/messages/en";

/** The parts of `ConsumptionOut` the model reads. */
export type ConsumptionData = {
  intervals: readonly IntervalOut[];
  gaps: readonly GapOut[];
  window: { start: string; end: string };
};

export type SegmentKind = "step" | "zero" | "gap" | "invalid";

export type Segment = {
  key: string;
  kind: SegmentKind;
  startMs: number;
  endMs: number;
  /** Plot height, for a step or zero segment; `null` for a band. */
  y: number | null;
  kindLabel: string;
  span: string;
  readout: string;
};

export type ChartPoint = { x: number; y: number | null };

export type Band = { key: string; startMs: number; endMs: number; invalid: boolean };

export type TableRow = {
  key: string;
  kind: SegmentKind;
  from: string;
  to: string;
  length: string;
  /** `null` on a gap, which shows "No measured usage" instead of a number. */
  kwh: string | null;
  rate: string | null;
  note: string;
};

export type Tick = { value: number; label: string };

export type ChartModel = {
  windowStartMs: number;
  windowEndMs: number;
  points: ChartPoint[];
  bands: Band[];
  /** Ordered steps and bands that tile the window. */
  segments: Segment[];
  rows: TableRow[];
  yTop: number;
  yTicks: number[];
  xTicks: Tick[];
  hasMeasured: boolean;
  defaultSegmentIndex: number;
};

const notAvailable = en.usage.notAvailable;

function twoPlaces(value: string | null): string {
  const parsed = value === null ? null : parseDecimal(value);
  return parsed === null ? notAvailable : formatDecimal(parsed, 2);
}

/** Copy for a gap, by its `reason` and for invalid intervals `interval_reason`. */
export function gapNote(gap: Pick<GapOut, "reason" | "interval_reason">): string {
  const key = gap.reason === "invalid_interval" ? gap.interval_reason : gap.reason;
  return key !== null && Object.hasOwn(en.usage.reasons, key)
    ? en.usage.reasons[key]
    : en.usage.reasonFallback;
}

/** The next number of the form 1, 2, or 5 times a power of ten above `value`. */
export function niceTop(value: number): number {
  if (!(value > 0) || !Number.isFinite(value)) {
    return 1;
  }
  const magnitude = 10 ** Math.floor(Math.log10(value));
  for (const factor of [1, 2, 5, 10]) {
    const top = factor * magnitude;
    if (top > value) {
      return top;
    }
  }
  return 20 * magnitude;
}

const WEEKLY_TICKS_UP_TO_MS = 32 * 86_400_000;

/** Month starts for long ranges, weekly marks for the 30 day range. */
export function xTicksFor(startMs: number, endMs: number, zone: string): Tick[] {
  const ticks: Tick[] = [];
  const firstLocal = new Intl.DateTimeFormat("en-CA", { timeZone: zone }).format(startMs);
  if (endMs - startMs <= WEEKLY_TICKS_UP_TO_MS) {
    for (let day = 0; ; day += 7) {
      const iso = zonedInstant(addLocalDays(firstLocal, day), "00:00", zone);
      const value = Date.parse(iso);
      if (value >= endMs) {
        return ticks;
      }
      ticks.push({ value, label: formatDateTime(iso, "monthDay", zone) ?? "" });
    }
  }
  let [year, month] = firstLocal.split("-").map(Number);
  for (;;) {
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
    const date = `${year}-${String(month).padStart(2, "0")}-01`;
    const value = Date.parse(zonedInstant(date, "00:00", zone));
    if (value >= endMs) {
      return ticks;
    }
    const name = new Intl.DateTimeFormat("en-US", {
      month: "short",
      timeZone: "UTC",
    }).format(Date.UTC(year, month - 1, 1));
    ticks.push({ value, label: month === 1 ? `${name} ${year}` : name });
  }
}

export function toChartModel(response: ConsumptionData, zone: string): ChartModel {
  const windowStartMs = Date.parse(response.window.start);
  const windowEndMs = Date.parse(response.window.end);
  const measured = response.intervals.filter((interval) => interval.measured_in_window);

  const dated = (value: string, style: "monthDay" | "mediumDate") =>
    formatDateTime(value, style, zone) ?? notAvailable;
  const spanOf = (start: string, end: string) =>
    en.usage.span(dated(start, "monthDay"), dated(end, "monthDay"));

  const stepEntries = measured.map((interval) => {
    const rate = interval.kwh_per_day === null ? null : parseDecimal(interval.kwh_per_day);
    const zero = rate !== null && isZeroDecimal(rate);
    // An unknown or unreadable rate is not plotted: a break, never a zero.
    const y = rate === null ? null : Number(interval.kwh_per_day);
    const length = formatLength(interval.duration) ?? notAvailable;
    const note = en.usage.averageOver(length);
    const rateText = twoPlaces(interval.kwh_per_day);
    const kwhText = twoPlaces(interval.consumption_kwh);
    const span = spanOf(interval.start, interval.end);
    const kind: SegmentKind = zero ? "zero" : "step";
    return {
      segment: {
        key: `step-${interval.start}`,
        kind,
        startMs: Date.parse(interval.start),
        endMs: Date.parse(interval.end),
        y: y !== null && Number.isFinite(y) ? y : null,
        kindLabel: zero ? en.usage.kindZero : en.usage.kindMeasured,
        span,
        readout: en.usage.readoutStep(span, rateText, kwhText, note.toLowerCase()),
      } satisfies Segment,
      row: {
        key: `step-${interval.start}`,
        kind,
        from: dated(interval.start, "mediumDate"),
        to: dated(interval.end, "mediumDate"),
        length,
        kwh: kwhText,
        rate: rateText,
        note,
      } satisfies TableRow,
    };
  });

  const gapEntries = response.gaps.map((gap, index) => {
    const invalid = gap.reason === "invalid_interval";
    const kind: SegmentKind = invalid ? "invalid" : "gap";
    const note = gapNote(gap);
    const length = formatLength(gap.duration) ?? notAvailable;
    const span = spanOf(gap.start, gap.end);
    const key = `gap-${index}-${gap.start}`;
    return {
      segment: {
        key,
        kind,
        startMs: Date.parse(gap.start),
        endMs: Date.parse(gap.end),
        y: null,
        kindLabel: invalid ? en.usage.kindInvalid : en.usage.kindGap,
        span,
        readout: en.usage.readoutBand(span, length, note),
      } satisfies Segment,
      row: {
        key,
        kind,
        from: dated(gap.start, "mediumDate"),
        to: dated(gap.end, "mediumDate"),
        length,
        kwh: null,
        rate: null,
        note,
      } satisfies TableRow,
    };
  });

  const entries = [...stepEntries, ...gapEntries].sort(
    (a, b) => a.segment.startMs - b.segment.startMs,
  );
  const segments = entries.map((entry) => entry.segment);

  // (start, rate), (end, rate), (end, null): no vertical joins between steps.
  const points: ChartPoint[] = stepEntries
    .map((entry) => entry.segment)
    .sort((a, b) => a.startMs - b.startMs)
    .flatMap((step) => [
      { x: step.startMs, y: step.y },
      { x: step.endMs, y: step.y },
      { x: step.endMs, y: null },
    ]);

  const largest = Math.max(0, ...stepEntries.map((entry) => entry.segment.y ?? 0));
  const yTop = niceTop(largest);

  let defaultSegmentIndex = segments.length - 1;
  for (let index = segments.length - 1; index >= 0; index -= 1) {
    if (segments[index].y !== null) {
      defaultSegmentIndex = index;
      break;
    }
  }

  return {
    windowStartMs,
    windowEndMs,
    points,
    bands: gapEntries.map(({ segment }) => ({
      key: segment.key,
      startMs: segment.startMs,
      endMs: segment.endMs,
      invalid: segment.kind === "invalid",
    })),
    segments,
    rows: entries.map((entry) => entry.row).reverse(),
    yTop,
    yTicks: [0, 1, 2, 3, 4, 5].map((step) => Number(((step * yTop) / 5).toPrecision(6))),
    xTicks: xTicksFor(windowStartMs, windowEndMs, zone),
    hasMeasured: measured.length > 0,
    defaultSegmentIndex,
  };
}

/** Every drawn item keeps at least this click and tap width (design README). */
export const MIN_HIT_PX = 12;

/**
 * The segment under pixel `x` inside a plot of `plotWidth` pixels. A thin
 * segment's hit area grows to `MIN_HIT_PX`, and the narrowest match wins, so a
 * 3 day step in a 365 day view can still be reached by pointer.
 */
export function segmentIndexAtX(
  segments: readonly Pick<Segment, "startMs" | "endMs">[],
  x: number,
  plotWidth: number,
  windowStartMs: number,
  windowEndMs: number,
): number | null {
  if (segments.length === 0 || plotWidth <= 0 || windowEndMs <= windowStartMs) {
    return null;
  }
  const scale = plotWidth / (windowEndMs - windowStartMs);
  let found: number | null = null;
  let narrowest = Number.POSITIVE_INFINITY;
  segments.forEach((segment, index) => {
    const left = (segment.startMs - windowStartMs) * scale;
    const right = (segment.endMs - windowStartMs) * scale;
    const width = right - left;
    const grow = Math.max(0, (MIN_HIT_PX - width) / 2);
    if (x >= left - grow && x < right + grow && width < narrowest) {
      found = index;
      narrowest = width;
    }
  });
  return found;
}
