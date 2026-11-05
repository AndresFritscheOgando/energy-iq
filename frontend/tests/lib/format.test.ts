/** Dates shown in America/Santo_Domingo (spec 0010 AC-16). */
import { describe, expect, it } from "vitest";

import { formatDateTime } from "@/lib/format";

describe("formatDateTime", () => {
  it("shows a UTC instant after local midnight as the previous Santo Domingo day", () => {
    // 02:30 UTC on Nov 5 is 22:30 on Nov 4 in Santo Domingo (UTC-4).
    expect(formatDateTime("2026-11-05T02:30:00Z", "date")).toBe("November 4, 2026");
  });

  it("shows the same day once Santo Domingo passes midnight", () => {
    expect(formatDateTime("2026-11-05T04:00:00Z", "date")).toBe("November 5, 2026");
  });

  it("includes the local time by default", () => {
    expect(formatDateTime("2026-11-05T02:30:00Z")).toBe("November 4, 2026 at 10:30 PM");
  });

  it("honours an explicit offset", () => {
    expect(formatDateTime("2026-11-05T02:30:00+05:00", "date")).toBe("November 4, 2026");
  });

  it.each(["not a date", "", "2026-11-05", "2026-11-05T02:30:00", "2026-13-45T99:99:00Z"])(
    "returns null for %j, never Invalid Date",
    (value) => {
      expect(formatDateTime(value)).toBeNull();
    },
  );
});
