/**
 * The one formatter for dates and times shown to users (spec 0010 AC-16).
 * The backend sends ISO 8601 strings with an explicit offset (UTC `Z`);
 * users see them in `America/Santo_Domingo`.
 */
export const DISPLAY_TIME_ZONE = "America/Santo_Domingo";

// An explicit offset is required, so a value is never read in the host zone.
const ISO_INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;

const STYLES = {
  date: { dateStyle: "long" },
  dateTime: { dateStyle: "long", timeStyle: "short" },
  mediumDate: { dateStyle: "medium" },
  mediumDateTime: { dateStyle: "medium", timeStyle: "short" },
  monthDay: { month: "short", day: "numeric" },
  time: { timeStyle: "short" },
} as const satisfies Record<string, Intl.DateTimeFormatOptions>;

export type DateTimeStyle = keyof typeof STYLES;

const cached = new Map<string, Intl.DateTimeFormat>();

function formatter(style: DateTimeStyle, zone: string): Intl.DateTimeFormat {
  const key = `${style}|${zone}`;
  let found = cached.get(key);
  if (found === undefined) {
    found = new Intl.DateTimeFormat("en-US", { timeZone: zone, ...STYLES[style] });
    cached.set(key, found);
  }
  return found;
}

/** The formatted value, or `null` when it is not a usable ISO 8601 instant. */
export function formatDateTime(
  value: string,
  style: DateTimeStyle = "dateTime",
  zone: string = DISPLAY_TIME_ZONE,
): string | null {
  if (!ISO_INSTANT.test(value)) {
    return null;
  }
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) {
    return null;
  }
  return formatter(style, zone).format(instant);
}

const LOCAL_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Format a plain `YYYY-MM-DD` with no zone conversion, or `null` when it is
 * not a real date. A date only reading keeps the day the user chose.
 */
export function formatLocalDate(
  value: string,
  style: "date" | "mediumDate" = "date",
): string | null {
  const match = LOCAL_DATE.exec(value);
  if (match === null) {
    return null;
  }
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const instant = new Date(Date.UTC(year, month - 1, day));
  if (instant.getUTCMonth() !== month - 1 || instant.getUTCDate() !== day) {
    return null;
  }
  return formatter(style, "UTC").format(instant);
}
