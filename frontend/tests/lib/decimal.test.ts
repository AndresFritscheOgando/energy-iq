/** Exact decimals (spec 0011 child 0001 AC-7, AC-9; child 0002 AC-2). */
import { describe, expect, it } from "vitest";

import {
  compareDecimal,
  formatDecimal,
  formatExact,
  formatPercent,
  parseDecimal,
  type Decimal,
} from "@/lib/decimal";

const d = (text: string): Decimal => {
  const value = parseDecimal(text);
  if (value === null) {
    throw new Error(`bad fixture ${text}`);
  }
  return value;
};

describe("parseDecimal", () => {
  it.each(["0", "0.000000", "13049", "13049.5", "999999999999.999999", "1234567890123456.25"])(
    "accepts %s",
    (text) => {
      expect(parseDecimal(text)).not.toBeNull();
    },
  );

  it.each(["", " 1", "1 ", "-1", "+1", "1.", ".5", "1,5", "1e3", "abc", "NaN", "0x10"])(
    "returns null for %j and never throws",
    (text) => {
      expect(parseDecimal(text)).toBeNull();
    },
  );
});

describe("compareDecimal", () => {
  it.each([
    ["9.5", "10", -1],
    ["10", "9.5", 1],
    ["13049.000000", "13049", 0],
    ["999999999999.999999", "999999999999.999998", 1],
    ["1234567890123456789.5", "1234567890123456789.25", 1],
    ["0.1", "0.10", 0],
  ])("%s against %s is %i", (a, b, expected) => {
    expect(compareDecimal(d(a), d(b))).toBe(expected);
  });

  it("is exact where a float would round both sides to the same number", () => {
    expect(compareDecimal(d("9007199254740993"), d("9007199254740992"))).toBe(1);
  });
});

describe("formatDecimal", () => {
  it.each([
    ["0", 2, "0.00"],
    ["0.000000", 2, "0.00"],
    ["1234567.5", 2, "1,234,567.50"],
    ["1.005", 2, "1.00"],
    ["1.015", 2, "1.02"],
    ["1.025", 2, "1.02"],
    ["1.0251", 2, "1.03"],
    ["0.995", 2, "1.00"],
    ["999.995", 2, "1,000.00"],
    ["12.5", 0, "12"],
    ["13.5", 0, "14"],
    ["1234567890123456.125", 2, "1,234,567,890,123,456.12"],
  ])("%s at %i places is %s (half even)", (value, places, expected) => {
    expect(formatDecimal(d(value), places)).toBe(expected);
  });
});

describe("formatExact", () => {
  it.each([
    ["13049.000000", "13,049"],
    ["13049.500000", "13,049.5"],
    ["0.000001", "0.000001"],
    ["0", "0"],
    ["999999999999.999999", "999,999,999,999.999999"],
  ])("%s is %s, never rounded", (value, expected) => {
    expect(formatExact(d(value))).toBe(expected);
  });
});

describe("formatPercent", () => {
  const both = { hasGaps: true, hasMeasured: true };

  it.each([
    ["0.8400", both, "84%"],
    ["0.8450", both, "84%"],
    ["0.8550", both, "86%"],
    ["0.9960", both, "over 99%"],
    ["1.0000", both, "over 99%"],
    ["0.0040", both, "under 1%"],
    ["0.0000", both, "under 1%"],
    ["1.0000", { hasGaps: false, hasMeasured: true }, "100%"],
    ["0.0000", { hasGaps: true, hasMeasured: false }, "0%"],
    ["0.9940", both, "99%"],
    ["0.0060", both, "1%"],
  ])("%s with %j is %s", (ratio, flags, expected) => {
    expect(formatPercent(d(ratio), flags)).toBe(expected);
  });
});
