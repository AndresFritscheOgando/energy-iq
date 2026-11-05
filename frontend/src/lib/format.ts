/**
 * The one formatter for dates and times shown to users (spec 0010 AC-16).
 * The backend sends ISO 8601 strings with an explicit offset (UTC `Z`);
 * users see them in `America/Santo_Domingo`.
 */
export const DISPLAY_TIME_ZONE = "America/Santo_Domingo";

// An explicit offset is required, so a value is never read in the host zone.
const ISO_INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;

const formatters = {
  date: new Intl.DateTimeFormat("en-US", {
    timeZone: DISPLAY_TIME_ZONE,
    dateStyle: "long",
  }),
  dateTime: new Intl.DateTimeFormat("en-US", {
    timeZone: DISPLAY_TIME_ZONE,
    dateStyle: "long",
    timeStyle: "short",
  }),
};

export type DateTimeStyle = keyof typeof formatters;

/** The formatted value, or `null` when it is not a usable ISO 8601 instant. */
export function formatDateTime(value: string, style: DateTimeStyle = "dateTime"): string | null {
  if (!ISO_INSTANT.test(value)) {
    return null;
  }
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) {
    return null;
  }
  return formatters[style].format(instant);
}
