/** Local time to UTC and the chart window (spec 0011 child 0001 AC-6; child 0002 AC-1). */
import { describe, expect, it } from "vitest";

import { formatDateTime, formatLocalDate } from "@/lib/format";
import {
  DEFAULT_RANGE,
  addLocalDays,
  localToday,
  nextLongerRange,
  parseRange,
  windowFor,
  zonedInstant,
} from "@/lib/zoned-time";

const SD = "America/Santo_Domingo";
const NY = "America/New_York";
const DAY = 86_400_000;

describe("zonedInstant", () => {
  it.each([
    ["2026-11-03", "12:00", SD, "2026-11-03T16:00:00Z"],
    ["2026-01-15", "00:00", SD, "2026-01-15T04:00:00Z"],
    ["2026-07-01", "23:59", SD, "2026-07-02T03:59:00Z"],
    ["2026-01-15", "12:00", NY, "2026-01-15T17:00:00Z"],
    ["2026-07-15", "12:00", NY, "2026-07-15T16:00:00Z"],
  ])("%s %s in %s is %s", (date, time, zone, expected) => {
    expect(zonedInstant(date, time, zone)).toBe(expected);
  });

  it("moves a time the spring change skips forward to the first valid instant", () => {
    // 2026-03-08 02:30 does not exist in New York; 03:00 EDT is 07:00Z.
    expect(zonedInstant("2026-03-08", "02:30", NY)).toBe("2026-03-08T07:00:00Z");
  });

  it("takes the earlier instant of a time the autumn change repeats", () => {
    // 2026-11-01 01:30 happens twice in New York; the first is EDT, 05:30Z.
    expect(zonedInstant("2026-11-01", "01:30", NY)).toBe("2026-11-01T05:30:00Z");
  });

  it("is exact on either side of each change", () => {
    expect(zonedInstant("2026-03-08", "01:59", NY)).toBe("2026-03-08T06:59:00Z");
    expect(zonedInstant("2026-03-08", "03:00", NY)).toBe("2026-03-08T07:00:00Z");
    expect(zonedInstant("2026-11-01", "00:59", NY)).toBe("2026-11-01T04:59:00Z");
    expect(zonedInstant("2026-11-01", "02:00", NY)).toBe("2026-11-01T07:00:00Z");
  });
});

describe("localToday and addLocalDays", () => {
  it("uses the property's zone, not the host's", () => {
    const now = new Date("2026-11-05T02:30:00Z");
    expect(localToday(SD, now)).toBe("2026-11-04");
    expect(localToday("UTC", now)).toBe("2026-11-05");
    expect(localToday("Asia/Tokyo", now)).toBe("2026-11-05");
  });

  it("crosses months and years", () => {
    expect(addLocalDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addLocalDays("2026-03-01", -1)).toBe("2026-02-28");
  });
});

describe("windowFor", () => {
  const now = new Date("2026-11-14T15:00:00Z");

  it.each([
    ["30d", "2026-10-16T04:00:00Z"],
    ["90d", "2026-08-17T04:00:00Z"],
    ["365d", "2025-11-15T04:00:00Z"],
  ] as const)("%s in Santo Domingo ends at the start of tomorrow", (range, from) => {
    expect(windowFor(range, SD, now)).toEqual({ from, to: "2026-11-15T04:00:00Z" });
  });

  it("uses local midnight on both ends across a DST change", () => {
    const window = windowFor("30d", NY, new Date("2026-11-14T15:00:00Z"));
    // `from` is in EDT and `to` is in EST.
    expect(window).toEqual({ from: "2026-10-16T04:00:00Z", to: "2026-11-15T05:00:00Z" });
  });

  it.each([
    ["2026-07-01T12:00:00Z", NY],
    ["2026-11-14T12:00:00Z", NY],
    ["2026-03-08T12:00:00Z", NY],
    ["2028-03-01T12:00:00Z", SD],
    ["2026-11-14T12:00:00Z", SD],
    ["2026-11-14T12:00:00Z", "Australia/Lord_Howe"],
  ])("365d never exceeds the API's 366 day limit at %s in %s", (instant, zone) => {
    const { from, to } = windowFor("365d", zone, new Date(instant));
    expect(Date.parse(to) - Date.parse(from)).toBeLessThanOrEqual(366 * DAY);
  });

  it("is stable through the day, so the query key doesn't change", () => {
    const morning = windowFor("90d", SD, new Date("2026-11-14T05:00:00Z"));
    const night = windowFor("90d", SD, new Date("2026-11-15T03:59:00Z"));
    expect(night).toEqual(morning);
  });
});

describe("parseRange", () => {
  it.each(["30d", "90d", "365d"] as const)("keeps %s", (value) => {
    expect(parseRange(value)).toBe(value);
  });

  it.each([undefined, "", "7d", "90D", "constructor", ["30d", "90d"]])(
    "treats %j as the default, with no error",
    (value) => {
      expect(parseRange(value)).toBe(DEFAULT_RANGE);
    },
  );

  it("knows the next longer preset", () => {
    expect(nextLongerRange("30d")).toBe("90d");
    expect(nextLongerRange("90d")).toBe("365d");
    expect(nextLongerRange("365d")).toBeNull();
  });
});

describe("formatting with a zone", () => {
  it("formatDateTime takes the property's zone", () => {
    const value = "2026-11-05T02:30:00Z";
    expect(formatDateTime(value, "date", "UTC")).toBe("November 5, 2026");
    expect(formatDateTime(value, "date", SD)).toBe("November 4, 2026");
    expect(formatDateTime(value, "date")).toBe("November 4, 2026");
    expect(formatDateTime(value, "time", NY)).toBe("9:30 PM");
  });

  it("formatLocalDate does no zone conversion", () => {
    expect(formatLocalDate("2026-11-05")).toBe("November 5, 2026");
    expect(formatLocalDate("2026-11-05", "mediumDate")).toBe("Nov 5, 2026");
  });

  it.each(["", "2026-13-01", "2026-02-30", "2026-11-05T00:00:00Z", "soon"])(
    "formatLocalDate returns null for %j",
    (value) => {
      expect(formatLocalDate(value)).toBeNull();
    },
  );
});
