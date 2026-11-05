/**
 * Local calendar arithmetic in a named time zone, through `Intl` (spec 0011).
 * The zone is always `PropertyOut.timezone`.
 */
export const RANGE_DAYS = { "30d": 30, "90d": 90, "365d": 365 } as const;
export type Range = keyof typeof RANGE_DAYS;
export const RANGES = Object.keys(RANGE_DAYS) as Range[];
export const DEFAULT_RANGE: Range = "90d";

export type ConsumptionWindow = { from: string; to: string };

const DAY_MS = 86_400_000;
const partsFormatters = new Map<string, Intl.DateTimeFormat>();

function partsFormatter(zone: string): Intl.DateTimeFormat {
  let found = partsFormatters.get(zone);
  if (found === undefined) {
    found = new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    partsFormatters.set(zone, found);
  }
  return found;
}

/** The wall clock in `zone` at `instant`, as if it were UTC milliseconds. */
function wallClock(instant: number, zone: string): number {
  const parts: Record<string, number> = {};
  for (const part of partsFormatter(zone).formatToParts(instant)) {
    if (part.type !== "literal") {
      parts[part.type] = Number(part.value);
    }
  }
  return Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second);
}

function offsetAt(instant: number, zone: string): number {
  return wallClock(instant, zone) - Math.floor(instant / 1000) * 1000;
}

function toIso(instant: number): string {
  return new Date(instant).toISOString().replace(".000Z", "Z");
}

/**
 * The UTC instant of a local date and time. A time a DST change skips moves
 * forward to the first valid instant; a time it repeats takes the earlier one.
 */
export function zonedInstant(date: string, time: string, zone: string): string {
  const [year, month, day] = date.split("-").map(Number);
  const [hour, minute, second = 0] = time.split(":").map(Number);
  const wall = Date.UTC(year, month - 1, day, hour, minute, second);

  // The offsets on either side of any change near this wall clock time.
  const before = offsetAt(wall - DAY_MS, zone);
  const after = offsetAt(wall + DAY_MS, zone);
  const candidates = [wall - before, wall - after].sort((a, b) => a - b);
  const valid = candidates.find((instant) => wallClock(instant, zone) === wall);
  if (valid !== undefined) {
    return toIso(valid);
  }

  // Skipped: the first valid instant is the change itself, between the two.
  let [low, high] = candidates;
  while (high - low > 1000) {
    const middle = Math.floor((low + high) / 2000) * 1000;
    if (offsetAt(middle, zone) === before) {
      low = middle;
    } else {
      high = middle;
    }
  }
  return toIso(high);
}

export function localToday(zone: string, now: Date = new Date()): string {
  return new Date(wallClock(now.getTime(), zone)).toISOString().slice(0, 10);
}

/** A local date moved by whole calendar days. */
export function addLocalDays(date: string, days: number): string {
  const [year, month, day] = date.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
}

/** `to` is the start of tomorrow; `from` is local midnight N days before it. */
export function windowFor(range: Range, zone: string, now: Date = new Date()): ConsumptionWindow {
  const tomorrow = addLocalDays(localToday(zone, now), 1);
  return {
    from: zonedInstant(addLocalDays(tomorrow, -RANGE_DAYS[range]), "00:00", zone),
    to: zonedInstant(tomorrow, "00:00", zone),
  };
}

/** Anything but a preset, including nothing or a repeated value, is the default. */
export function parseRange(value: string | string[] | undefined): Range {
  return typeof value === "string" && (RANGES as string[]).includes(value)
    ? (value as Range)
    : DEFAULT_RANGE;
}

export function nextLongerRange(range: Range): Range | null {
  return RANGES[RANGES.indexOf(range) + 1] ?? null;
}
