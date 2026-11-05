/** The chart model (spec 0011 child 0002 AC-3 to AC-7). */
import { describe, expect, it } from "vitest";

import type { GapOut, IntervalOut } from "@/lib/api/generated/model";
import {
  gapNote,
  niceTop,
  segmentIndexAtX,
  toChartModel,
  type ConsumptionData,
} from "@/lib/consumption/chart-model";
import { formatLength, parseDuration } from "@/lib/consumption/duration";
import { en } from "@/messages/en";

const SD = "America/Santo_Domingo";

function interval(
  start: string,
  end: string,
  rate: string,
  kwh: string,
  duration: string,
  extra: Partial<IntervalOut> = {},
): IntervalOut {
  return {
    start,
    end,
    kwh_per_day: rate,
    consumption_kwh: kwh,
    duration,
    event_ids: [],
    measured_in_window: true,
    previous_reading_id: "a",
    current_reading_id: "b",
    reason: null,
    status: "valid",
    ...extra,
  };
}

function gap(
  start: string,
  end: string,
  reason: GapOut["reason"],
  duration = "P1D",
  intervalReason: GapOut["interval_reason"] = null,
): GapOut {
  return {
    start,
    end,
    reason,
    duration,
    interval_reason: intervalReason,
    event_ids: [],
    previous_reading_id: null,
    current_reading_id: null,
  };
}

const WINDOW = { start: "2026-10-01T04:00:00Z", end: "2026-11-01T04:00:00Z" };

const MIXED: ConsumptionData = {
  window: WINDOW,
  intervals: [
    interval("2026-10-05T16:00:00Z", "2026-10-12T16:00:00Z", "4.000000", "28.000000", "P7D"),
    interval("2026-10-12T16:00:00Z", "2026-10-19T16:00:00Z", "0.000000", "0.000000", "P7D"),
    interval("2026-10-19T16:00:00Z", "2026-10-26T16:00:00Z", "0", "0", "P7D", {
      measured_in_window: false,
      status: "invalid",
      reason: "unexplained_decrease",
      kwh_per_day: null,
      consumption_kwh: null,
    }),
    interval("2026-10-26T16:00:00Z", "2026-11-05T16:00:00Z", "9.000000", "90.000000", "P10D", {
      measured_in_window: false,
    }),
  ],
  gaps: [
    gap("2026-10-01T04:00:00Z", "2026-10-05T16:00:00Z", "before_first_reading", "P4DT12H"),
    gap(
      "2026-10-19T16:00:00Z",
      "2026-10-26T16:00:00Z",
      "invalid_interval",
      "P7D",
      "unexplained_decrease",
    ),
    gap("2026-10-26T16:00:00Z", "2026-11-01T04:00:00Z", "partial_interval", "P5DT12H"),
  ],
};

describe("toChartModel", () => {
  const model = toChartModel(MIXED, SD);

  it("tiles the window exactly, with no hole and no overlap", () => {
    expect(model.segments[0].startMs).toBe(Date.parse(WINDOW.start));
    expect(model.segments.at(-1)?.endMs).toBe(Date.parse(WINDOW.end));
    for (let index = 1; index < model.segments.length; index += 1) {
      expect(model.segments[index].startMs).toBe(model.segments[index - 1].endMs);
    }
  });

  it("makes a zero rate a step and never a band", () => {
    const zero = model.segments.filter((segment) => segment.kind === "zero");
    expect(zero).toHaveLength(1);
    expect(zero[0].y).toBe(0);
    expect(model.rows.find((row) => row.kind === "zero")?.kwh).toBe("0.00");
    expect(model.bands.map((band) => band.startMs)).not.toContain(zero[0].startMs);
  });

  it("draws only measured intervals, so invalid and partial appear through their gap", () => {
    const steps = model.segments.filter((segment) => segment.y !== null);
    expect(steps).toHaveLength(2);
    expect(model.points.filter((point) => point.y === 9)).toEqual([]);
    expect(model.bands).toHaveLength(3);
    expect(model.bands.filter((band) => band.invalid)).toHaveLength(1);
  });

  it("separates steps with nulls, so adjacent steps have no vertical connector", () => {
    const start = Date.parse("2026-10-05T16:00:00Z");
    const end = Date.parse("2026-10-12T16:00:00Z");
    expect(model.points.slice(0, 3)).toEqual([
      { x: start, y: 4 },
      { x: end, y: 4 },
      { x: end, y: null },
    ]);
  });

  it("lists rows newest first, with gaps saying nothing numeric", () => {
    expect(model.rows.map((row) => row.kind)).toEqual(["gap", "invalid", "zero", "step", "gap"]);
    for (const row of model.rows.filter((item) => item.kind === "gap" || item.kind === "invalid")) {
      expect(row.kwh).toBeNull();
      expect(row.rate).toBeNull();
    }
  });

  it("uses exact strings that never passed through Number", () => {
    const large = toChartModel(
      {
        window: WINDOW,
        gaps: [],
        intervals: [
          interval(
            WINDOW.start,
            WINDOW.end,
            "1234567890123456.125",
            "9007199254740993.015",
            "P31D",
          ),
        ],
      },
      SD,
    );
    expect(large.rows[0].rate).toBe("1,234,567,890,123,456.12");
    expect(large.rows[0].kwh).toBe("9,007,199,254,740,993.02");
    expect(large.segments[0].readout).toContain("1,234,567,890,123,456.12 kWh per day");
  });

  it("writes the readout for a step and a band", () => {
    const step = model.segments.find((segment) => segment.kind === "step");
    expect(step?.readout).toBe("Oct 5 to Oct 12: 4.00 kWh per day, 28.00 kWh, average over 7 days");
    const band = model.segments.find((segment) => segment.kind === "invalid");
    expect(band?.readout).toBe(
      "Oct 19 to Oct 26, 7 days: No measured usage. The reading dropped with no recorded reset or replacement, so no usage is counted.",
    );
  });

  it("shows dates in the property's zone", () => {
    const utc = toChartModel(MIXED, "UTC");
    const edge: ConsumptionData = {
      window: WINDOW,
      gaps: [],
      intervals: [interval("2026-10-05T02:00:00Z", "2026-10-12T02:00:00Z", "1", "7", "P7D")],
    };
    expect(toChartModel(edge, SD).rows[0].from).toBe("Oct 4, 2026");
    expect(toChartModel(edge, "UTC").rows[0].from).toBe("Oct 5, 2026");
    expect(utc.segments).toHaveLength(model.segments.length);
  });

  it("selects the newest measured step by default, and handles none", () => {
    expect(model.segments[model.defaultSegmentIndex].kind).toBe("zero");
    const none = toChartModel(
      {
        window: WINDOW,
        intervals: [],
        gaps: [gap(WINDOW.start, WINDOW.end, "after_last_reading")],
      },
      SD,
    );
    expect(none.defaultSegmentIndex).toBe(0);
    expect(none.hasMeasured).toBe(false);
    expect(none.points).toEqual([]);
    expect(none.yTop).toBe(1);
  });

  it("puts axis ticks inside the window", () => {
    for (const tick of model.xTicks) {
      expect(tick.value).toBeGreaterThanOrEqual(model.windowStartMs);
      expect(tick.value).toBeLessThan(model.windowEndMs);
    }
    const year = toChartModel(
      {
        intervals: [],
        gaps: [],
        window: { start: "2025-11-15T04:00:00Z", end: "2026-11-15T04:00:00Z" },
      },
      SD,
    );
    expect(year.xTicks.map((tick) => tick.label)).toContain("Jan 2026");
    expect(year.xTicks).toHaveLength(12);
  });
});

describe("niceTop", () => {
  it.each([
    [0, 1],
    [0.19, 0.2],
    [1, 2],
    [4, 5],
    [5, 10],
    [14.6, 20],
    [62, 100],
    [999, 1000],
  ])("the next nice number above %d is %d", (value, top) => {
    expect(niceTop(value)).toBeCloseTo(top);
  });

  it("is 1 for an unusable value", () => {
    expect(niceTop(Number.NaN)).toBe(1);
    expect(niceTop(-1)).toBe(1);
  });
});

describe("gapNote", () => {
  it.each([
    ["before_first_reading", null, "Before your first reading."],
    ["after_last_reading", null, "No reading yet after this date."],
    ["no_intervals", null, "Not enough readings to measure usage."],
    [
      "partial_interval",
      null,
      "A span between two readings crosses the edge of this range, so it isn't counted here. Try a longer range.",
    ],
    [
      "invalid_interval",
      "unexplained_decrease",
      "The reading dropped with no recorded reset or replacement, so no usage is counted.",
    ],
    ["invalid_interval", "flagged_reading", "A reading here is flagged, so no usage is counted."],
    [
      "invalid_interval",
      "unapproved_event",
      "A meter event here isn't approved yet, so no usage is counted.",
    ],
    [
      "invalid_interval",
      "meter_boundary",
      "The meter was reset or replaced here, so usage isn't counted across it.",
    ],
    [
      "invalid_interval",
      "unsupported_event",
      "A meter event here can't be calculated yet, so no usage is counted.",
    ],
  ] as const)("%s with %s", (reason, intervalReason, text) => {
    expect(gapNote({ reason, interval_reason: intervalReason })).toBe(text);
  });

  it("falls back for an unknown value", () => {
    const unknown = { reason: "something_new", interval_reason: null } as unknown as GapOut;
    expect(gapNote(unknown)).toBe(en.usage.reasonFallback);
    const noReason = { reason: "invalid_interval", interval_reason: null } as GapOut;
    expect(gapNote(noReason)).toBe(en.usage.reasonFallback);
    const proto = { reason: "constructor", interval_reason: null } as unknown as GapOut;
    expect(typeof gapNote(proto)).toBe("string");
  });
});

describe("length text", () => {
  it.each([
    ["P1DT2H30M", "1 day"],
    ["PT6H", "6 hours"],
    ["PT1H", "1 hour"],
    ["PT1.5S", "under 1 hour"],
    ["PT0S", "under 1 hour"],
    ["P1DT12H", "2 days"],
    ["P2DT12H", "2 days"],
    ["P3DT12H", "4 days"],
    ["P43D", "43 days"],
    ["PT1H30M", "2 hours"],
    ["PT2H30M", "2 hours"],
    ["PT23H59M", "24 hours"],
  ])("%s is %s (half even)", (duration, text) => {
    expect(formatLength(duration)).toBe(text);
  });

  it("parses fractional seconds exactly", () => {
    expect(parseDuration("PT1.5S")).toBe(BigInt(1_500_000));
    expect(parseDuration("PT0.000001S")).toBe(BigInt(1));
  });

  it.each(["", "P", "PT", "soon", "P1W", "1D"])("rejects %j", (text) => {
    expect(formatLength(text)).toBeNull();
  });
});

describe("segmentIndexAtX", () => {
  const start = 0;
  const end = 1000;
  const segments = [
    { startMs: 0, endMs: 400 },
    { startMs: 400, endMs: 410 },
    { startMs: 410, endMs: 1000 },
  ];

  it("maps x to the segment under it", () => {
    expect(segmentIndexAtX(segments, 100, 1000, start, end)).toBe(0);
    expect(segmentIndexAtX(segments, 800, 1000, start, end)).toBe(2);
  });

  it("gives a thin segment a 12 pixel hit area, and it wins over a neighbor", () => {
    expect(segmentIndexAtX(segments, 402, 1000, start, end)).toBe(1);
    expect(segmentIndexAtX(segments, 399, 1000, start, end)).toBe(1);
    expect(segmentIndexAtX(segments, 395, 1000, start, end)).toBe(0);
  });

  it("scales with the plot width", () => {
    expect(segmentIndexAtX(segments, 50, 100, start, end)).toBe(2);
  });

  it("returns null with nothing to hit", () => {
    expect(segmentIndexAtX([], 10, 100, start, end)).toBeNull();
    expect(segmentIndexAtX(segments, 10, 0, start, end)).toBeNull();
    expect(segmentIndexAtX(segments, -50, 1000, start, end)).toBeNull();
  });
});

describe("a measured interval with no usable rate", () => {
  it("is not plotted, so it never reads as zero use", () => {
    const model = toChartModel(
      {
        window: WINDOW,
        intervals: [
          interval("2026-10-05T16:00:00Z", "2026-10-12T16:00:00Z", "x", "1", "P7D", {
            kwh_per_day: null,
          }),
        ],
        gaps: [],
      },
      SD,
    );
    expect(model.segments[0].y).toBeNull();
    expect(model.segments[0].kind).toBe("step");
    expect(model.points.every((point) => point.y === null)).toBe(true);
  });
});
