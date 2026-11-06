/**
 * Length text from the API's ISO 8601 `duration` (spec 0011 child 0002 AC-6).
 * Exact: microseconds as `BigInt`, whole counts rounded half even, so the
 * client never subtracts timestamps.
 */
import { en } from "@/messages/en";

const DURATION = /^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)(?:\.(\d{1,6}))?S)?)?$/;

const MICROS_PER_SECOND = BigInt(1_000_000);
const MICROS_PER_HOUR = BigInt(3600) * MICROS_PER_SECOND;
const MICROS_PER_DAY = BigInt(24) * MICROS_PER_HOUR;
const ONE = BigInt(1);
const TWO = BigInt(2);

/** Total microseconds, or `null` when the text is not an API duration. */
export function parseDuration(text: string): bigint | null {
  const match = DURATION.exec(text);
  if (match === null || text === "P" || text.endsWith("T")) {
    return null;
  }
  const [, days = "0", hours = "0", minutes = "0", seconds = "0", fraction = ""] = match;
  return (
    BigInt(days) * MICROS_PER_DAY +
    BigInt(hours) * MICROS_PER_HOUR +
    BigInt(minutes) * BigInt(60) * MICROS_PER_SECOND +
    BigInt(seconds) * MICROS_PER_SECOND +
    BigInt(fraction.padEnd(6, "0") || "0")
  );
}

function roundHalfEven(value: bigint, unit: bigint): bigint {
  const quotient = value / unit;
  const twiceRemainder = (value % unit) * TWO;
  if (twiceRemainder > unit || (twiceRemainder === unit && quotient % TWO === ONE)) {
    return quotient + ONE;
  }
  return quotient;
}

/** "7 days", "6 hours", or "under 1 hour". Unreadable text gives `null`. */
export function formatLength(duration: string): string | null {
  const micros = parseDuration(duration);
  if (micros === null) {
    return null;
  }
  if (micros >= MICROS_PER_DAY) {
    return en.usage.length.days(roundHalfEven(micros, MICROS_PER_DAY).toString());
  }
  if (micros >= MICROS_PER_HOUR) {
    return en.usage.length.hours(roundHalfEven(micros, MICROS_PER_HOUR).toString());
  }
  return en.usage.length.underHour;
}
