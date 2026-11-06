/**
 * Exact decimal handling for values the API sends as strings (spec 0011).
 * kWh, rates, and ratios never pass through `Number`, so nothing shown can
 * pick up binary float error. Scaled `BigInt`, half even rounding.
 */
const DECIMAL = /^[0-9]+(\.[0-9]+)?$/;
const ZERO = BigInt(0);
const ONE = BigInt(1);
const TWO = BigInt(2);
const TEN = BigInt(10);
const HUNDRED = BigInt(100);

/** `digits / 10^scale`. */
export type Decimal = { readonly digits: bigint; readonly scale: number };

/** Any length of digits, or `null` (never throws, so a render can't crash). */
export function parseDecimal(text: string): Decimal | null {
  if (typeof text !== "string" || !DECIMAL.test(text)) {
    return null;
  }
  const [whole, fraction = ""] = text.split(".");
  return { digits: BigInt(whole + fraction), scale: fraction.length };
}

function power(exponent: number): bigint {
  return TEN ** BigInt(exponent);
}

export function compareDecimal(a: Decimal, b: Decimal): -1 | 0 | 1 {
  const scale = Math.max(a.scale, b.scale);
  const left = a.digits * power(scale - a.scale);
  const right = b.digits * power(scale - b.scale);
  return left < right ? -1 : left > right ? 1 : 0;
}

export function isZeroDecimal(value: Decimal): boolean {
  return value.digits === ZERO;
}

/** The value times `10^places`, rounded half even. */
function roundedDigits(value: Decimal, places: number): bigint {
  if (value.scale <= places) {
    return value.digits * power(places - value.scale);
  }
  const divisor = power(value.scale - places);
  const quotient = value.digits / divisor;
  const twiceRemainder = (value.digits % divisor) * TWO;
  if (twiceRemainder > divisor || (twiceRemainder === divisor && quotient % TWO === ONE)) {
    return quotient + ONE;
  }
  return quotient;
}

function groupThousands(whole: string): string {
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** Rounded half even to exactly `places`, with thousands grouped. */
export function formatDecimal(value: Decimal, places: number): string {
  const text = roundedDigits(value, places)
    .toString()
    .padStart(places + 1, "0");
  const whole = text.slice(0, text.length - places);
  const fraction = text.slice(text.length - places);
  return places === 0 ? groupThousands(whole) : `${groupThousands(whole)}.${fraction}`;
}

/** Every digit kept, trailing zeros trimmed, thousands grouped. Never rounds. */
export function formatExact(value: Decimal): string {
  const text = value.digits.toString().padStart(value.scale + 1, "0");
  const whole = text.slice(0, text.length - value.scale);
  const fraction = text.slice(text.length - value.scale).replace(/0+$/, "");
  return fraction ? `${groupThousands(whole)}.${fraction}` : groupThousands(whole);
}

/**
 * A ratio as a whole percent, half even. It never says 100% with gaps
 * present, or 0% with something measured.
 */
export function formatPercent(
  ratio: Decimal,
  { hasGaps, hasMeasured }: { hasGaps: boolean; hasMeasured: boolean },
): string {
  const percent = roundedDigits({ digits: ratio.digits * HUNDRED, scale: ratio.scale }, 0);
  if (percent === HUNDRED && hasGaps) {
    return "over 99%";
  }
  if (percent === ZERO && hasMeasured) {
    return "under 1%";
  }
  return `${percent.toString()}%`;
}
